import { createClient } from '@supabase/supabase-js';

const $ = (id) => document.getElementById(id);
const gate = $('authGate');
const loginForm = $('loginForm');
const signupForm = $('signupForm');
const redeemForm = $('redeemForm');
const recoveryForm = $('recoveryForm');
const accountPanel = $('accountPanel');
const config = window.TRADING_AUTH_CONFIG || {};
let client = null;
let syncInFlight = false;
let ledgerChannel = null;

function showMessage(message, kind = 'info') {
  const node = $('authMessage');
  node.textContent = message;
  node.className = `auth-message ${kind}`;
  node.hidden = false;
}
function clearMessage() { $('authMessage').hidden = true; }
function setBusy(form, busy) {
  form.querySelectorAll('button').forEach((button) => { button.disabled = busy; });
}
function gateMode(mode) {
  loginForm.hidden = mode !== 'login';
  signupForm.hidden = mode !== 'signup';
  redeemForm.hidden = mode !== 'redeem';
  recoveryForm.hidden = mode !== 'recovery';
  $('authUnavailable').hidden = true;
  $('authForms').hidden = false;
  clearMessage();
}
function showGate() {
  if (ledgerChannel && client) { client.removeChannel(ledgerChannel); ledgerChannel = null; }
  document.body.classList.remove('account-ready');
  document.body.style.overflow = 'hidden';
  document.querySelector('.wrap').inert = true;
  document.querySelector('.wrap').setAttribute('aria-hidden', 'true');
  gate.hidden = false;
  accountPanel.hidden = true;
  $('accountEmail').textContent = '—';
  $('accountId').textContent = '—';
  $('demoBalance').textContent = '—';
  $('ledgerRows').replaceChildren();
  $('ledgerStatus').textContent = 'Masuk untuk melihat saldo simulasi.';
  $('inviteOutput').hidden = true;
  $('inviteCodeOutput').textContent = '';
  delete $('inviteCodeOutput').dataset.code;
  $('inviteAdmin').hidden = true;
  $('demoAdmin').hidden = true;
  $('loginPassword').value = '';
  $('signupPassword').value = '';
  $('signupCode').value = '';
  $('redeemCode').value = '';
  $('recoveryPassword').value = '';
  $('creditUserId').value = ''; $('creditAmount').value = ''; $('creditMemo').value = ''; $('creditMessage').textContent = '';
  window.accountAccessGranted = false;
}
async function showMember(user) {
  document.body.classList.add('account-ready');
  document.body.style.overflow = '';
  document.querySelector('.wrap').inert = false;
  document.querySelector('.wrap').removeAttribute('aria-hidden');
  gate.hidden = true;
  accountPanel.hidden = false;
  window.accountAccessGranted = true;
  $('accountEmail').textContent = user.email || 'Akun terverifikasi';
  $('accountId').textContent = `ID akun · ${user.id}`;
  await loadWallet();
  await checkAdmin(user.id);
  $('loginPassword').value = ''; $('signupPassword').value = ''; $('signupCode').value = ''; $('redeemCode').value = ''; $('recoveryPassword').value = '';
  if (ledgerChannel) await client.removeChannel(ledgerChannel);
  ledgerChannel = client.channel(`demo-ledger:${user.id}`).on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'demo_ledger', filter: `user_id=eq.${user.id}` }, () => loadWallet()).subscribe();
  if (typeof poll === 'function') poll();
}
async function loadWallet() {
  $('demoBalance').textContent = 'memuat…';
  $('ledgerRows').replaceChildren();
  const [balanceResult, ledgerResult] = await Promise.all([
    client.from('demo_balance').select('balance_idr,currency_code').maybeSingle(),
    client.from('demo_ledger').select('id,amount_idr,entry_type,memo,created_at').order('created_at', { ascending: false }).limit(8),
  ]);
  if (balanceResult.error) {
    $('demoBalance').textContent = 'tidak tersedia';
    $('ledgerStatus').textContent = 'Data saldo simulasi gagal dimuat. Coba muat ulang setelah koneksi pulih.';
    return;
  }
  const balance = Number(balanceResult.data?.balance_idr || 0);
  $('demoBalance').textContent = `${Number(balance).toLocaleString('id-ID')} SIM_IDR`;
  const rows = ledgerResult.data || [];
  if (ledgerResult.error || rows.length === 0) {
    $('ledgerStatus').textContent = ledgerResult.error ? 'Riwayat transaksi belum dapat dimuat.' : 'Belum ada perubahan saldo simulasi.';
    return;
  }
  $('ledgerStatus').textContent = 'Riwayat saldo simulasi akun ini';
  const fragment = document.createDocumentFragment();
  for (const row of rows) {
    const item = document.createElement('li');
    const title = document.createElement('span');
    title.textContent = row.memo;
    const value = document.createElement('b');
    const amount = Number(row.amount_idr);
    value.textContent = `${amount > 0 ? '+' : ''}${amount.toLocaleString('id-ID')} SIM_IDR`;
    value.className = amount > 0 ? 'positive' : 'negative';
    const date = document.createElement('small');
    date.textContent = new Date(row.created_at).toLocaleString('id-ID');
    item.append(title, value, date);
    fragment.append(item);
  }
  $('ledgerRows').append(fragment);
}
async function checkAdmin(userId) {
  const { data, error } = await client.rpc('is_current_user_admin');
  const admin = !error && data === true;
  $('inviteAdmin').hidden = !admin;
  $('demoAdmin').hidden = !admin;
  if (!admin) return;
  $('inviteAdmin').dataset.user = userId;
}
async function syncSession() {
  if (!client || syncInFlight) return;
  syncInFlight = true;
  try {
    const { data: { user }, error } = await client.auth.getUser();
    if (error || !user) { showGate(); gateMode('login'); return; }
    const { data: profile, error: profileError } = await client.from('account_profiles').select('access_status').eq('user_id', user.id).maybeSingle();
    if (profileError) { showGate(); gateMode('login'); showMessage('Tidak dapat memverifikasi akses akun. Coba lagi sebentar.', 'error'); return; }
    if (profile?.access_status === 'active') { await showMember(user); return; }
    showGate(); gateMode('redeem');
    if (profile?.access_status === 'blocked') showMessage('Akses akun ini dinonaktifkan. Hubungi pemilik situs.', 'error');
    else showMessage('Akun terdaftar. Masukkan kode undangan yang diberikan pemilik untuk membuka dashboard.', 'info');
  } finally { syncInFlight = false; }
}
async function redeemCode(code) {
  const clean = String(code || '').trim().toUpperCase();
  if (!/^[A-F0-9]{48}$/.test(clean)) throw new Error('Kode undangan harus 48 karakter heksadesimal.');
  const { data, error } = await client.functions.invoke('redeem-invite', { body: { code: clean } });
  if (error || data?.access !== 'granted') throw new Error(data?.error === 'invalid_or_expired_code' ? 'Kode tidak valid, sudah dipakai, atau kedaluwarsa.' : 'Kode belum dapat diverifikasi. Coba lagi.');
}

const cfgReady = typeof config.supabaseUrl === 'string' && /^https:\/\//.test(config.supabaseUrl)
  && typeof config.publishableKey === 'string' && config.publishableKey.length > 20;
if (!cfgReady) {
  $('authUnavailable').hidden = false;
  $('authForms').hidden = true;
  $('authSetupText').textContent = 'Portal akun sedang dikonfigurasi. Login dan pendaftaran belum aktif, jadi jangan masukkan kata sandi atau kode di halaman ini.';
  showGate();
} else {
  client = createClient(config.supabaseUrl, config.publishableKey, {
    auth: { autoRefreshToken: true, persistSession: true, detectSessionInUrl: true, flowType: 'pkce' },
  });
  showGate();
  gateMode('login');
  syncSession();
  client.auth.onAuthStateChange((event) => {
    if (event === 'PASSWORD_RECOVERY') { showGate(); gateMode('recovery'); showMessage('Atur kata sandi baru untuk akunmu.', 'info'); return; }
    queueMicrotask(syncSession);
  });
}

$('showSignup').addEventListener('click', () => gateMode('signup'));
$('showLogin').addEventListener('click', () => gateMode('login'));
$('loginForm').addEventListener('submit', async (event) => {
  event.preventDefault(); clearMessage(); setBusy(loginForm, true);
  try {
    const { error } = await client.auth.signInWithPassword({ email: $('loginEmail').value.trim(), password: $('loginPassword').value });
    if (error) throw error;
    await syncSession();
  } catch (error) { showMessage(error.message || 'Login gagal. Periksa email dan kata sandi.', 'error'); }
  finally { setBusy(loginForm, false); }
});
$('signupForm').addEventListener('submit', async (event) => {
  event.preventDefault(); clearMessage(); setBusy(signupForm, true);
  const email = $('signupEmail').value.trim();
  const password = $('signupPassword').value;
  const code = $('signupCode').value;
  try {
    if (!/^[A-Fa-f0-9]{48}$/.test(code.trim())) throw new Error('Masukkan kode undangan 48 karakter yang diberikan pemilik.');
    if (password.length < 12) throw new Error('Gunakan kata sandi minimal 12 karakter.');
    const { data: inviteValid, error: inviteError } = await client.rpc('validate_access_invite', { p_code: code.trim().toUpperCase(), p_email: email });
    if (inviteError || inviteValid !== true) throw new Error('Kode tidak valid, kedaluwarsa, atau tidak ditujukan ke email ini.');
    const { data, error } = await client.auth.signUp({ email, password });
    if (error) throw error;
    if (data.session) {
      await redeemCode(code);
      await syncSession();
    } else {
      showMessage('Akun dibuat. Buka email untuk verifikasi, lalu login dan masukkan kode undangan untuk mengaktifkan akses.', 'success');
      gateMode('login');
    }
  } catch (error) { showMessage(error.message || 'Pendaftaran gagal. Periksa data lalu coba lagi.', 'error'); }
  finally { setBusy(signupForm, false); }
});
$('redeemForm').addEventListener('submit', async (event) => {
  event.preventDefault(); clearMessage(); setBusy(redeemForm, true);
  try { await redeemCode($('redeemCode').value); await syncSession(); }
  catch (error) { showMessage(error.message || 'Kode undangan gagal diverifikasi.', 'error'); }
  finally { setBusy(redeemForm, false); }
});
$('recoveryForm').addEventListener('submit', async (event) => {
  event.preventDefault(); clearMessage(); setBusy(recoveryForm, true);
  try {
    const password = $('recoveryPassword').value;
    if (password.length < 12) throw new Error('Gunakan kata sandi minimal 12 karakter.');
    const { error } = await client.auth.updateUser({ password });
    if (error) throw error;
    showMessage('Kata sandi berhasil diperbarui. Silakan login kembali.', 'success');
    await client.auth.signOut(); gateMode('login');
  } catch (error) { showMessage(error.message || 'Kata sandi belum dapat diperbarui.', 'error'); }
  finally { setBusy(recoveryForm, false); }
});
$('forgotPassword').addEventListener('click', async () => {
  const email = $('loginEmail').value.trim();
  if (!email) { showMessage('Masukkan email akun terlebih dahulu.', 'error'); return; }
  try {
    const { error } = await client.auth.resetPasswordForEmail(email, { redirectTo: `${location.origin}${location.pathname}` });
    if (error) throw error;
    showMessage('Jika akun terdaftar, tautan pemulihan akan dikirim ke email.', 'success');
  } catch { showMessage('Permintaan pemulihan belum dapat dikirim. Coba lagi nanti.', 'error'); }
});
$('copyAccountId').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText((await client.auth.getUser()).data.user.id); $('copyAccountId').textContent = 'ID tersalin'; }
  catch { showMessage('ID akun tidak dapat disalin otomatis.', 'info'); }
});
let creditRequestKey = crypto.randomUUID();
$('adminCreditForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const amount = Number($('creditAmount').value);
  const message = $('creditMessage');
  if (!Number.isSafeInteger(amount) || amount === 0) { message.textContent = 'Masukkan perubahan saldo berupa bilangan bulat selain nol.'; return; }
  const button = $('adminCreditForm').querySelector('button[type="submit"]'); button.disabled = true;
  message.textContent = 'Menyimpan perubahan simulasi…';
  try {
    const { data, error } = await client.rpc('admin_adjust_demo_balance', {
      p_user_id: $('creditUserId').value.trim(), p_amount_idr: amount,
      p_memo: $('creditMemo').value.trim(), p_idempotency_key: creditRequestKey,
    });
    if (error) throw error;
    message.textContent = `Tersimpan. Saldo simulasi akun: ${Number(data).toLocaleString('id-ID')} SIM_IDR.`;
    creditRequestKey = crypto.randomUUID();
    $('creditAmount').value = ''; $('creditMemo').value = '';
    await loadWallet();
  } catch (error) { message.textContent = error.code === '42501' ? 'Perubahan ditolak: akses admin tidak sah.' : (error.message || 'Perubahan simulasi gagal.'); }
  finally { button.disabled = false; }
});
$('signOut').addEventListener('click', async () => {
  await client.auth.signOut({ scope: 'local' }); showGate(); gateMode('login');
});
$('issueInvite').addEventListener('click', async () => {
  $('inviteOutput').hidden = true;
  const inviteEmail = $('inviteEmail').value.trim();
  if (!inviteEmail) { showMessage('Masukkan email orang yang kamu izinkan.', 'error'); return; }
  $('issueInvite').disabled = true;
  try {
    const { data, error } = await client.functions.invoke('issue-invite', { body: { ttl_days: 7, email: inviteEmail } });
    if (error || !data?.code) throw new Error('Kode undangan belum dapat dibuat.');
    $('copyInvite').textContent = 'Salin kode';
    $('inviteCodeOutput').textContent = `${data.code} · untuk ${inviteEmail} · berlaku 7 hari`;
    $('inviteCodeOutput').dataset.code = data.code;
    $('inviteOutput').hidden = false;
  } catch (error) { showMessage(error.message || 'Gagal membuat kode undangan.', 'error'); }
  finally { $('issueInvite').disabled = false; }
});
$('copyInvite').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('inviteCodeOutput').dataset.code || ''); $('copyInvite').textContent = 'Tersalin'; }
  catch { showMessage('Salin kode undangan secara manual.', 'info'); }
});
