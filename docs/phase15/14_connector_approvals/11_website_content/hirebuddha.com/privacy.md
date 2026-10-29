<!--
Page: https://hirebuddha.com/privacy  ·  Draft for counsel's review (SH-07, WEB-04).
Fill every [BRACKETED] value; check the "Before you publish" list in ../README.md:
several statements here describe engineering that must be live first.
-->

# HireBuddha Privacy Policy

**Effective:** [EFFECTIVE DATE] · **Last updated:** [LAST UPDATED DATE]

HireBuddha is a product of **Buddha Cognitive Lab Private Limited** ("Buddha Cognitive Lab", "we", "us"), a company incorporated in India (CIN [CIN]), with its registered office at [REGISTERED OFFICE ADDRESS AS ON THE CERTIFICATE OF INCORPORATION]. This policy explains what personal data HireBuddha collects, why, how long we keep it, who we share it with, and the choices and rights you have. It covers the HireBuddha website (hirebuddha.com), the HireBuddha application, its APIs, and HireBuddha's AI account manager, Pragya.

Our company website, buddhalab.in, has [its own privacy policy](https://buddhalab.in/privacy).

## 1. Summary

* Businesses use HireBuddha to build **AI employees**: agents that answer customers, handle e-mail, publish to social media and do other work. A business can connect its own accounts (for example Gmail, Outlook, a Facebook Page, Instagram, WhatsApp, LinkedIn, X, YouTube, Google Ads or GitHub) so its AI employees can work there.
* We use the data a business gives us, or connects, **only to provide HireBuddha to that business**. We do not sell personal data, and we do not use it for advertising.
* **We do not use data from connected accounts to train AI models**, ours or anyone else's.
* **A person approves every message, post, comment reply, upload or campaign change** that an AI employee wants to send or make on a connected account before it goes out.
* Data is stored in Microsoft Azure's Central India region, encrypted, and each business's data is kept apart from every other business's.
* You can disconnect any account, or close your business account, at any time. See [Data deletion](https://hirebuddha.com/data-deletion).

## 2. Who is responsible for your data

* **Account data** (the people who sign up for and use HireBuddha, and billing): Buddha Cognitive Lab decides how it is used. Under India's Digital Personal Data Protection Act, 2023 ("DPDP Act") we are the **Data Fiduciary**; under the EU and UK GDPR we are the **controller**.
* **Business data** (what a business puts into HireBuddha or connects to it, including data about its own customers, contacts and callers): the **business** decides how it is used, and we process it on its behalf. We are a **Data Processor** (DPDP Act) or **processor** (GDPR). If you are a customer of a business that uses HireBuddha, that business is responsible for your data; you can also contact us (section 13).
* A **Data Processing Agreement** is available to business customers on request at [privacy@hirebuddha.com](mailto:privacy@hirebuddha.com).

## 3. The data we collect

**When you use the website**

* What you type into the contact form: name, work e-mail, company, team size, and what you would like to automate.
* Your conversations with **Pragya**, by text or voice. Voice is used only to answer you in that conversation; we keep the transcript, not the recording, [FOR HOW LONG / CONFIRM WHETHER ANY RECORDING IS KEPT]. Pragya runs on our own service at api.fluidbuddha.com.
* Technical data your browser sends (IP address, browser and device type, pages requested), kept in our server logs for up to 30 days for security.

**When you use HireBuddha**

* **Account data:** name, e-mail address, phone number (if given), password (stored only as a hash), your company and role, sign-in records and devices.
* **Billing data:** billing contact, billing address, GSTIN (for Indian businesses), invoices and payment records. Card and bank details are entered on Razorpay's page and held by Razorpay, not by us.
* **Business data:** the AI employees you build and their instructions; documents and knowledge you upload; records, contacts and campaigns; conversations, calls, transcripts and recordings handled by your AI employees; their runs, results and logs; usage and cost records.
* **Connected account data:** described for each provider in section 6.
* **Support:** what you tell our team, and the access you grant them (section 8).

We do not ask for sensitive personal data (such as health, financial account numbers or government identifiers) and ask businesses not to give HireBuddha such data unless they need it for their own lawful purpose and have told the people concerned.

## 4. How we use data, and our legal basis

| Purpose | Data | Basis |
|---|---|---|
| Provide HireBuddha: run your AI employees, connect your accounts, show results | Account, business and connected account data | Contract with the business; for business data, the business's instructions |
| Keep accounts secure, prevent abuse and fraud, detect prompt injection | All | Legitimate interests; legal obligations |
| Bill for usage, collect payment, keep tax records | Account and billing data, usage records | Contract; legal obligations (Indian GST and company law) |
| Support you when you ask | What you share, and access you grant | Contract; your consent for access to business content |
| Improve HireBuddha's reliability (for example, fixing a failure) | Run metadata: errors, timings, costs, model choices | Legitimate interests. **Never** the content of connected accounts, and never to train AI models |
| Answer website enquiries and Pragya conversations | Website data | Your consent, or steps you ask us to take before a contract |
| Tell you about changes to HireBuddha or these terms | Account data | Contract; legitimate interests. Marketing e-mails only with your consent, and you can unsubscribe at any time |

**Learning in HireBuddha is per business.** An AI employee can improve from its own business's runs (for example, remembering a customer's preferences). That learning stays inside that business's workspace. We do not use one business's data to improve another business's AI employees, and we do not train or fine-tune any general or shared AI model, including our own BabyBuddha models, on customer data or connected account data.

## 5. AI models

HireBuddha's AI employees use large language models to read and write. To produce a feature, the text an AI employee is working on (which can include connected account data) is sent to the model provider chosen for that step: [CONFIRM THE ENABLED PROVIDERS, E.G.: Google Cloud Vertex AI (Gemini and Claude models), Microsoft Azure OpenAI, OpenAI, Anthropic] or HireBuddha's own models. A business may restrict which providers its AI employees use, or bring its own provider key.

We use these providers under terms that **forbid them from training their models on the data we send** and limit how long they keep it. We do not keep copies of model inputs or outputs for training.

## 6. Connected accounts

A business connects an account by signing in with the provider and approving the access HireBuddha asks for. HireBuddha shows what it will read and do before you continue. The access tokens are encrypted with a key that belongs to that business alone, and are never shown again. Below is what HireBuddha does with each kind of account.

### 6.1 Google (Gmail, Google Drive, YouTube, Google Ads, Sign in with Google)

* **Gmail:** HireBuddha reads new mail in the mailbox you connect so your AI employees can work on it, labels the messages it has handled, saves replies as drafts, and sends replies after a person on your team approves each one. It never deletes mail.
* **Google Drive:** HireBuddha opens only the files you choose and the files it creates, and saves the files your AI employees produce.
* **YouTube:** HireBuddha uses **YouTube API Services**. It uploads the videos a person on your team approves to the channel you connect, with the title, description, audience and privacy setting shown on the approval, and shows your team the channel's videos, playlists, comments and analytics. YouTube data is used only for your business. Data from your channel other than analytics is kept for at most 30 days unless HireBuddha refreshes it from YouTube; analytics is kept while your connection is valid, and we check that every 30 days. By using YouTube features in HireBuddha you also agree to the [YouTube Terms of Service](https://www.youtube.com/t/terms). Google's handling of your data is described in the [Google Privacy Policy](https://policies.google.com/privacy).
* **Google Ads:** HireBuddha reads the Google Ads account you connect and its results, and creates or changes campaigns only after a person on your team approves the change. Ad spend is billed by Google to your Google Ads account.
* **Sign in with Google:** we receive your name, e-mail address and Google account identifier to sign you in.
* **Limited Use.** HireBuddha's use and transfer to any other app of information received from Google APIs will adhere to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.
* **No AI training on Google Workspace data.** We do not use, transfer or sell data from Google Workspace APIs (such as Gmail and Drive) to develop, improve or train generalised or non-personalised AI or machine learning models, and we keep no such data for that purpose.
* **Revoking access:** you can disconnect in HireBuddha (*Connections*), or remove HireBuddha from your Google Account's [third-party access page](https://myaccount.google.com/connections) or [security settings page](https://security.google.com/settings/security/permissions). When you revoke access, we delete the Google data we hold for that connection within 7 days, including YouTube data.

### 6.2 Meta (Facebook Pages, Instagram, WhatsApp Business)

* **Facebook Pages:** HireBuddha lists the Pages you manage and, for the Page you choose, reads its posts, comments, Messenger conversations and insights; it publishes the posts and comment replies a person on your team approves, and answers Messenger messages within Meta's 24-hour messaging window. Automated replies say they come from an AI assistant, and a person can take over.
* **Instagram:** HireBuddha reads your professional account's posts, comments and Direct messages, and publishes the posts, comment replies and message answers your team approves.
* **WhatsApp Business:** HireBuddha sends and receives WhatsApp messages for your business's number. Your AI employee answers your customers within WhatsApp's customer service window, and sends approved message templates only to customers who opted in. **WhatsApp messages are not used to train AI models.**
* We record which Facebook user connected each account, so that we can act on Meta's requests.
* **Deletion:** removing HireBuddha from your Facebook settings disconnects the accounts you connected. You can ask us to delete your data through Facebook, or as described on our [Data deletion](https://hirebuddha.com/data-deletion) page; Meta gives you a confirmation code and a page showing what we deleted.

### 6.3 Microsoft (Outlook and Microsoft 365 mail)

HireBuddha reads new mail in the mailbox you connect, saves replies as drafts and sends replies after a person on your team approves each one, using Microsoft Graph. In many organisations a Microsoft 365 administrator approves HireBuddha once for the organisation. Microsoft does not let apps revoke their own access: after you disconnect, a user can remove HireBuddha at [myapps.microsoft.com](https://myapps.microsoft.com) and an administrator in Microsoft Entra.

### 6.4 LinkedIn (LinkedIn Pages)

HireBuddha publishes posts to the LinkedIn Page you choose after a person on your team approves each one, and shows your team how the Page's posts perform.

* LinkedIn members' data (such as a comment on your post and the commenter's name and headline) is shown **only to people of the business that owns the Page**.
* It is kept **no longer than LinkedIn allows**: members' activity (comments, mentions) for at most 48 hours, and other members' profile data for at most 24 hours. Post statistics are kept for up to one year.
* We do **not** use LinkedIn member data for sales, recruiting, advertising or lead generation; we do not export it, sell it, or combine it with other data to build profiles.

### 6.5 X (formerly Twitter)

HireBuddha posts to the X account you connect, replies only where a person on your team approves it, and reads the account's timeline and mentions so your AI employees can draft posts. Posts are billed per post at X's price. When content is deleted on X, or X asks us to, we delete it **within 24 hours**; when you disconnect, we delete all X data within 10 business days. X data is **never used to train AI models**.

### 6.6 GitHub

HireBuddha's GitHub App is installed on the repositories you choose, so your AI employees can read code, push branches, open pull requests, comment and report checks there. It reaches no other repositories. Uninstalling the App ends the access.

### 6.7 Mailboxes, CRMs, API keys and MCP servers

A business can also connect a mailbox with an app password (IMAP and SMTP), a CRM such as HubSpot with its own token, other services with an API key, or its own MCP server. The password, token or key is stored encrypted under the business's own key and used only for that business. Disconnecting deletes it; to cancel it at the provider too, remove the app password or token there.

### 6.8 What disconnecting does

When you disconnect an account, HireBuddha revokes its access at the provider where the provider allows it, deletes the stored tokens or password, and deletes the mail, comments, messages and other events it stored from that account. The history of what your AI employees did with that account stays in your workspace until you delete it or close your account, subject to the provider limits above. Details: [Data deletion](https://hirebuddha.com/data-deletion).

## 7. Protection against misuse of AI employees

* **Approvals.** A message, post, comment reply, video upload or Google Ads change that an AI employee wants to make on a connected account waits in your team's *Approvals* until a person approves it, and is then carried out exactly as approved.
* **Prompt injection.** Mail, comments and messages from outside your business are screened for instructions aimed at the AI and marked as quoted data, so an AI employee does not follow them. Content found to carry such an attack is withheld from the AI.

## 8. Who can see your data

* **People in your business,** according to the roles your administrators give them.
* **A partner (reseller)** that manages your account, only to the extent you allow.
* **Our staff,** only to run and support the service: they do not read the content of your connected accounts (such as e-mails, messages or comments) unless you grant support access for a limited time, unless it is needed to investigate security incidents or abuse, or unless the law requires it.
* **Service providers** that process data for us (section 9).
* **Authorities,** when the law requires it; we will tell the affected business unless the law forbids it.
* **A buyer or successor,** if our business is merged or sold, under the same protections.

## 9. Service providers (sub-processors)

| Provider | What for | Where |
|---|---|---|
| Microsoft Azure | Hosting, databases, storage, key management | India (Central India) |
| [CONFIRM: Google Cloud] | [AI models through Vertex AI; hosting of hirebuddha.com] | [REGIONS] |
| [CONFIRM: Microsoft Azure OpenAI / OpenAI / Anthropic] | AI models | [REGIONS] |
| [CONFIRM: Twilio, Tata Tele Business Services, Plivo] | Phone calls, numbers and messaging | [REGIONS] |
| Razorpay | Payments | India |
| Google Workspace | Our e-mail with you | [REGIONS] |
| [CONFIRM: transactional e-mail service] | Account e-mails (sign-up, password reset, notices) | [REGIONS] |

The current list is published at [hirebuddha.com/subprocessors](https://hirebuddha.com/subprocessors). Each provider is bound by a contract that limits its use of data to the service it provides to us.

## 10. Where data is stored, and transfers

HireBuddha's databases and files are hosted in India (Microsoft Azure, Central India). Some providers in section 9, such as AI model providers, may process data in other countries. Where we transfer personal data of people in the European Economic Area, the UK or Switzerland, we use the safeguards the law requires, such as the European Commission's Standard Contractual Clauses. We do not transfer personal data to a country to which the Government of India has restricted transfers under the DPDP Act.

## 11. How long we keep data

| Data | Kept |
|---|---|
| Business data and connected account data | While the business uses HireBuddha, and the provider limits in section 6 always apply. Deleted when the business deletes it, disconnects the account (section 6.8) or closes its account |
| After a business asks to close its account | A 30-day grace period in which it can change its mind and export its data; then everything is erased within one working day, except the records below |
| Invoices, credit notes, payment and wallet records, partner statements, our audit trail | 8 years, as Indian tax and company law require; personal details not needed for that purpose are removed |
| Backups and logs | Database point-in-time restore: 7 days. Weekly backups: 5 weeks. Deleted files: 14 days. Logs: 30 days. Each business's data is encrypted with its own key, which is destroyed when the business is erased, so any copy left in a backup cannot be read |
| Website enquiries and Pragya conversations | [24 MONTHS] from the last contact, unless you become a customer |

## 12. Security

Each business's data is held in its own database. Secrets such as tokens and passwords are encrypted with AES-256-GCM under a key that belongs to that business, protected by Azure Key Vault. Connections use TLS. Access by our staff is limited, logged and reviewed. If a breach of personal data occurs, we will tell the affected businesses and authorities as the law requires. To report a vulnerability, write to [security@hirebuddha.com](mailto:security@hirebuddha.com).

## 13. Your rights and choices

Depending on where you live, you can ask us to:

* tell you what personal data we hold about you and how we use it, and give you a copy;
* correct, complete or update it;
* delete it (subject to the records we must keep);
* stop or limit using it, or object to its use, including for direct marketing;
* withdraw your consent, where we rely on it;
* move it to another service (portability);
* and, under the DPDP Act, **nominate** another person to exercise your rights if you die or become unable to.

If your data is held for a business that uses HireBuddha (for example, you are its customer), ask that business first; we will help it answer you. You can also write to us, and we will forward your request to the business or act on it where we decide how the data is used.

We will answer within 30 days, and may ask you to confirm your identity. You may complain to the **Data Protection Board of India**, or to your local data protection authority if you are in the EU or UK.

**Withdrawing consent** does not affect what was done before. If you withdraw consent needed to provide the service, we may not be able to continue providing it.

## 14. Cookies and similar technologies

HireBuddha uses only what it needs to work: a secure cookie that keeps you signed in (up to 7 days) and your browser's local storage for your session and preferences. hirebuddha.com uses no advertising or analytics cookies. [IF ANALYTICS ARE ADDED: name the tool, what it collects, and the consent banner.]

## 15. Children

HireBuddha is a service for businesses and is not meant for anyone under 18. We do not knowingly collect personal data of children. Businesses must not use HireBuddha to process children's data without the verifiable consent of a parent or guardian where the law requires it.

## 16. Changes to this policy

We will post changes here and update the date at the top. If a change materially affects how we use your data, we will tell account administrators by e-mail or in HireBuddha at least 30 days before it takes effect. Earlier versions are available on request.

## 17. Contact and Grievance Officer

* **Privacy questions and requests:** [privacy@hirebuddha.com](mailto:privacy@hirebuddha.com)
* **Grievance Officer** (Information Technology Act, 2000 and the rules under it; DPDP Act): [NAME], [DESIGNATION], Buddha Cognitive Lab Private Limited, [REGISTERED OFFICE ADDRESS], [grievance@hirebuddha.com], [PHONE]. We acknowledge a grievance within 24 hours and resolve it within 15 days, or sooner where the law requires.
* **Post:** Buddha Cognitive Lab Private Limited, [REGISTERED OFFICE ADDRESS], India.
