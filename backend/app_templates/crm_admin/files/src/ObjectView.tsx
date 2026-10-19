import { FormEvent, useEffect, useState } from "react";
import * as hb from "./lib/hb-data";

type Field = { type: string; label?: string; required?: boolean; values?: string[] };
type Obj = { label: string; plural: string; fields: Record<string, Field> };

const INPUT: Record<string, string> = { integer: "number", decimal: "number", money: "number", date: "date",
  datetime: "datetime-local", email: "email", url: "url", phone: "tel" };

function show(value: unknown) {
  if (value === null || value === undefined) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export default function ObjectView({ name, object }: { name: string; object: Obj }) {
  const [page, setPage] = useState<hb.Page | null>(null);
  const [editing, setEditing] = useState<Record<string, any> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const columns = Object.entries(object.fields).filter(([, f]) => f.type !== "json").slice(0, 6);

  const load = (after?: string) =>
    hb.list(name, after ? { "page[after]": after } : {}).then(setPage).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [name]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const values: Record<string, unknown> = {};
    for (const [field, spec] of Object.entries(object.fields)) {
      const raw = form.get(field);
      if (raw === null) continue;
      if (spec.type === "boolean") values[field] = raw === "on";
      else if (raw === "") values[field] = null;
      else values[field] = ["integer"].includes(spec.type) ? Number(raw) : raw;
    }
    try {
      if (editing?.id) await hb.update(name, editing.id, editing.row_version, values);
      else await hb.create(name, values);
      setEditing(null);
      load();
    } catch (caught: any) {
      setError(caught.message);
    }
  }

  return (
    <section>
      <h1>{object.plural}</h1>
      {error && <p className="error">{error}</p>}
      {editing ? (
        <form onSubmit={save}>
          {Object.entries(object.fields).map(([field, spec]) => (
            <label key={field}>
              {spec.label || field}
              {spec.type === "enum" ? (
                <select name={field} defaultValue={editing[field] ?? ""}>
                  <option value="" />
                  {(spec.values || []).map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
              ) : spec.type === "boolean" ? (
                <input name={field} type="checkbox" defaultChecked={Boolean(editing[field])} style={{ width: "auto" }} />
              ) : (
                <input name={field} type={INPUT[spec.type] || "text"} required={spec.required}
                  defaultValue={show(editing[field])} />
              )}
            </label>
          ))}
          <button type="submit">Save</button>{" "}
          <button type="button" className="link" onClick={() => setEditing(null)}>Cancel</button>
        </form>
      ) : (
        <>
          <button onClick={() => setEditing({})}>New {object.label}</button>
          <table>
            <thead><tr>{columns.map(([field, spec]) => <th key={field}>{spec.label || field}</th>)}</tr></thead>
            <tbody>
              {page?.items.map((record) => (
                <tr key={record.id} onClick={() => setEditing(record)} style={{ cursor: "pointer" }}>
                  {columns.map(([field]) => <td key={field}>{show(record[field])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          {page?.next && <button className="link" onClick={() => load(page.next!)}>Next page</button>}
        </>
      )}
    </section>
  );
}
