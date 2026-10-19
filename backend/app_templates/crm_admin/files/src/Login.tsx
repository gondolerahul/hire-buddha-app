import { FormEvent, useState } from "react";
import * as hb from "./lib/hb-data";
import app from "./app.json";

export default function Login({ onSignedIn }: { onSignedIn: (user: any) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError(null);
    try {
      onSignedIn(await hb.login(String(form.get("email")), String(form.get("password"))));
    } catch (caught: any) {
      setError(caught.message || "Could not sign in");
    }
  }

  async function magicLink(event: FormEvent<HTMLButtonElement>) {
    const form = (event.currentTarget as HTMLButtonElement).form!;
    const email = String(new FormData(form).get("email") || "");
    if (!email) return setError("Enter your e-mail first");
    await hb.requestMagicLink(email).catch(() => undefined);
    setSent(true);
  }

  return (
    <main style={{ maxWidth: 360 }}>
      <h1>{app.display_name}</h1>
      <form onSubmit={signIn}>
        <label>E-mail<input name="email" type="email" required autoComplete="username" /></label>
        <label>Password<input name="password" type="password" autoComplete="current-password" /></label>
        {error && <p className="error">{error}</p>}
        {sent && <p>If that address may sign in, a link is on its way.</p>}
        <button type="submit">Sign in</button>{" "}
        <button type="button" className="link" onClick={magicLink}>E-mail me a sign-in link</button>
      </form>
    </main>
  );
}
