(async () => {
  const errors = { state: "Sign-in expired. Try again.", oauth: "GitHub sign-in failed.", denied: "That GitHub account isn't allowed here.", rate: "Too many attempts. Wait a few minutes." };
  const q = new URLSearchParams(location.search);
  const err = document.getElementById("err");
  if (q.get("error")) err.textContent = errors[q.get("error")] || "Sign-in failed.";
  const opts = await (await fetch("/auth/options")).json();
  if (opts.oauth) document.getElementById("oauth").classList.remove("hidden");
  const form = document.getElementById("code-form");
  if (opts.code) form.classList.remove("hidden");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.textContent = "";
    const r = await fetch("/auth/code", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: document.getElementById("code").value }) });
    if (r.ok) location.href = "/";
    else err.textContent = (await r.json().catch(() => ({}))).error || "Sign-in failed.";
  });
})();
