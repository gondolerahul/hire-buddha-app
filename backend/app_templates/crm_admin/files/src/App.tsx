import { useEffect, useState } from "react";
import * as hb from "./lib/hb-data";
import Login from "./Login";
import ObjectView from "./ObjectView";
import app from "./app.json";

type Schema = { objects: Record<string, { label: string; plural: string; fields: Record<string, any> }> };

export default function App() {
  const [user, setUser] = useState<any>(null);
  const [schema, setSchema] = useState<Schema | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const magic = new URLSearchParams(window.location.search).get("hb_magic");
    const start = magic ? hb.verifyMagicLink(magic) : hb.signedIn() ? hb.me() : Promise.resolve(null);
    start.then(setUser).catch(() => setUser(null)).finally(() => {
      if (magic) window.history.replaceState(null, "", window.location.pathname);
    });
  }, []);

  useEffect(() => {
    if (!user) return;
    hb.schema().then((found: Schema) => {
      const objects = Object.fromEntries(Object.entries(found.objects).filter(([name]) => app.objects.includes(name)));
      setSchema({ objects });
      setCurrent((name) => name ?? Object.keys(objects)[0] ?? null);
    }).catch((caught) => setError(String(caught.message || caught)));
  }, [user]);

  if (!user) return <Login onSignedIn={setUser} />;
  return (
    <>
      <nav>
        <strong>{app.display_name}</strong>
        {schema && Object.entries(schema.objects).map(([name, obj]) => (
          <button key={name} className="link" onClick={() => setCurrent(name)}>{obj.plural}</button>
        ))}
        <span style={{ marginLeft: "auto" }}>{user.email}</span>
        <button className="link" onClick={() => hb.logout().then(() => setUser(null))}>Sign out</button>
      </nav>
      <main>
        {error && <p className="error">{error}</p>}
        {schema && current && schema.objects[current] && (
          <ObjectView key={current} name={current} object={schema.objects[current]} />
        )}
        {schema && !Object.keys(schema.objects).length && <p>Your role cannot see any records in this app.</p>}
      </main>
    </>
  );
}
