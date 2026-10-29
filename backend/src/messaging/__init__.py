"""Rules for conversations with a business's customers on Messenger, Instagram
and WhatsApp (META-E4, META-E5; docs/phase15/14_connector_approvals/10 §3.5).

* ``models`` — each conversation's state (last messages, a hand-off to a
  person) and each WhatsApp contact's opt-in, in the business's database.
* ``rules``  — the AI disclosure, the hand-off, the 24-hour service window and
  what a business-initiated WhatsApp message needs.
* ``api``    — the business's screens: conversations waiting for a person, opt-ins.
"""
