import { FormEvent, useState } from "react";
import { config, create, DataApiError } from "./lib/hb-data";

// The form creates one "{{form_object}}" record with the site's public key.
// Spam protection: a hidden field people never fill (the honeypot), at most
// one submission every 30 seconds from this browser, and the key's own rate
// limit at the Data API.
const OBJECT = "{{form_object}}";
const WAIT_MS = 30_000;

export default function ContactForm() {
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (form.get("website")) return; // the honeypot was filled: a bot
    const last = Number(localStorage.getItem("hb.form.last") || 0);
    if (Date.now() - last < WAIT_MS) {
      setError("Please wait a moment before sending again.");
      return;
    }
    setState("sending");
    setError(null);
    try {
      await create(OBJECT, {
        name: String(form.get("name") || ""),
        email: String(form.get("email") || ""),
        message: String(form.get("message") || ""),
      }, config().publicKey);
      localStorage.setItem("hb.form.last", String(Date.now()));
      setState("sent");
    } catch (caught) {
      setState("idle");
      setError(caught instanceof DataApiError ? caught.message : "Something went wrong. Please try again.");
    }
  }

  if (state === "sent") return <p>Thank you — we received your message.</p>;
  return (
    <form onSubmit={submit}>
      <label>Name<input name="name" required maxLength={120} /></label>
      <label>E-mail<input name="email" type="email" required maxLength={200} /></label>
      <label>Message<textarea name="message" rows={5} maxLength={4000} /></label>
      <label className="hidden" aria-hidden="true">Website<input name="website" tabIndex={-1} autoComplete="off" /></label>
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={state === "sending"}>{state === "sending" ? "Sending…" : "Send"}</button>
    </form>
  );
}
