import ContactForm from "./ContactForm";

export default function App() {
  return (
    <main>
      <h1>{{display_name}}</h1>
      <p className="lead">Tell us what you need and we will get back to you.</p>
      <ContactForm />
    </main>
  );
}
