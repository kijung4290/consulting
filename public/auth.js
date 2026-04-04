let supabase;

async function initSupabase() {
  try {
    const response = await fetch("/api/config");
    const config = await response.json();
    
    if (!config.supabaseUrl || !config.supabaseAnonKey) {
      const el = document.getElementById("authStatus");
      if(el) el.innerText = "서버에 Supabase가 아직 연동되지 않았습니다.";
      return;
    }
    
    supabase = window.supabase.createClient(config.supabaseUrl, config.supabaseAnonKey);
  } catch (e) {
    const el = document.getElementById("authStatus");
    if(el) el.innerText = "설정을 불러오는 중 오류가 발생했습니다.";
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  await initSupabase();
  if (!supabase) return;

  const googleLoginBtn = document.getElementById("googleLoginBtn");
  const authStatus = document.getElementById("authStatus");

  const { data: { session } } = await supabase.auth.getSession();
  if (session) {
    window.location.href = "/";
    return;
  }

  if (googleLoginBtn) {
    googleLoginBtn.addEventListener("click", async () => {
      googleLoginBtn.disabled = true;
      if (authStatus) {
        authStatus.style.color = "#666";
        authStatus.innerText = "구글 로그인 창으로 이동합니다... (팝업 차단을 해제해주세요)";
      }

      const { data, error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: window.location.origin
        }
      });

      if (error && authStatus) {
        authStatus.style.color = "#e11d48";
        authStatus.innerText = `로그인 실패: ${error.message}`;
        googleLoginBtn.disabled = false;
      }
    });
  }
});
