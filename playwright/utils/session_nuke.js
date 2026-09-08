(() => {
  // 1. Clear Storage APIs
  localStorage.clear();
  sessionStorage.clear();

  // 2. Aggressively expire cookies for current domain AND root domain
  const cookies = document.cookie.split(";");
  cookies.forEach(c => {
    const name = c.replace(/^ +/, "").split("=")[0];
    const expire = "=;expires=Thu, 01 Jan 1970 00:00:00 GMT";

    // Clear for current path
    document.cookie = name + expire + ";path=/";
    // Clear for root domain (Crucial for vCreative SSO)
    document.cookie = name + expire + ";path=/;domain=.vcreative.net";
  });

  return "State Cleared";
})()