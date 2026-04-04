let supabase;

async function initSupabase() {
  try {
    const response = await fetch("/api/config");
    const config = await response.json();
    
    if (!config.supabaseUrl || !config.supabaseAnonKey) {
      document.getElementById("authStatus").innerText = "서버에 Supabase가 아직 연동되지 않았습니다.";
      return;
    }
    
    supabase = window.supabase.createClient(config.supabaseUrl, config.supabaseAnonKey);
  } catch (e) {
    document.getElementById("authStatus").innerText = "설정을 불러오는 중 오류가 발생했습니다.";
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  await initSupabase();

  const authForm = document.getElementById("authForm");
  const emailInput = document.getElementById("email");
  const passwordInput = document.getElementById("password");
  const authStatus = document.getElementById("authStatus");
  const loginBtn = document.getElementById("loginBtn");
  const signupBtn = document.getElementById("signupBtn");

  if (!authForm || !supabase) return;

  authForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginBtn.disabled = true;
    authStatus.style.color = "#666";
    authStatus.innerText = "로그인 중...";

    const { data, error } = await supabase.auth.signInWithPassword({
      email: emailInput.value,
      password: passwordInput.value
    });

    if (error) {
      authStatus.style.color = "#e11d48";
      authStatus.innerText = "로그인 실패: 잘못된 이메일이거나 비밀번호입니다.";
      loginBtn.disabled = false;
    } else {
      localStorage.setItem("sb-access-token", data.session.access_token);
      window.location.href = "/";
    }
  });

  signupBtn.addEventListener("click", async () => {
    const email = emailInput.value;
    const password = passwordInput.value;
    
    if (!email || !password) {
      authStatus.style.color = "#e11d48";
      authStatus.innerText = "이메일과 비밀번호를 모두 입력해주세요.";
      return;
    }
    if (password.length < 6) {
      authStatus.style.color = "#e11d48";
      authStatus.innerText = "비밀번호는 최소 6자 이상이어야 합니다.";
      return;
    }
    
    signupBtn.disabled = true;
    authStatus.style.color = "#666";
    authStatus.innerText = "회원가입 요청 중...";

    const { data, error } = await supabase.auth.signUp({
      email,
      password
    });

    signupBtn.disabled = false;

    if (error) {
      authStatus.style.color = "#e11d48";
      authStatus.innerText = `회원가입 실패: ${error.message}`;
    } else {
      authStatus.style.color = "green";
      authStatus.innerText = "가입이 접수되었습니다. 관리자 승인 후 이용 가능합니다.";
      emailInput.value = "";
      passwordInput.value = "";
    }
  });
});
