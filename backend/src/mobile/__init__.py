"""
Mobile dialer support (docs/mobile-dialer-app).

The Android app places two carrier calls from the rep's SIM — one to the
tenant DID answered by the AI agent, one to the lead — and merges them. This
package identifies which lead an inbound AI leg belongs to (caller-ID match +
DTMF token), gates the AI until the merge, and serves the app's REST API.
"""
