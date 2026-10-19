const sections = [
  { title: "What we do", body: "Tell visitors what {{display_name}} offers and who it is for." },
  { title: "Why us", body: "Three reasons a customer should choose you. Keep each one short." },
  { title: "Get in touch", body: "Say how to reach you: an e-mail address, a phone number, opening hours." },
];

export default function App() {
  return (
    <main>
      <h1>{{display_name}}</h1>
      <p className="lead">A website built with HireBuddha. Edit src/App.tsx to make it yours.</p>
      {sections.map((section) => (
        <section key={section.title}>
          <h2>{section.title}</h2>
          <p>{section.body}</p>
        </section>
      ))}
    </main>
  );
}
