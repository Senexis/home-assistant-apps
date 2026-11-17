# Changelog

## 3.27.2-31

- The Console no longer shows the empty `>>>` prompts Bridge prints after each sync update.

## 3.27.2-30

- Sync progress and time left are tracked per account.
- The status badge says how many accounts are synchronizing, like "Synchronizing 1 of 2 accounts".

## 3.27.2-29

- Synchronizing shows the time left again, counting down to the second.

## 3.27.2-28

- Fixed: Restart, Repair, Reset and Check now had their labels pushed to the right.
- Accounts show their full address (masked) instead of only the user name.
- Smaller account and settings buttons.

## 3.27.2-27

- Better support for several accounts: each account has its own row with its address mode and its own Mailbox details. With two or more accounts the rows start folded.
- In split mode, an address picker shows each address's own login.
- Header fits on a phone.

## 3.27.2-26

- Shorter help texts and a more general Console description.
- Documentation rewritten to match the page, with IMAP and SMTP set-up side by side.

## 3.27.2-25

- Fixed: the SSL / STARTTLS choices could show no selection after Bridge restarted.
- Maintenance and Updates use rows with a button on the right, like Proton's app.

## 3.27.2-24

- IMAP and SMTP connection are SSL / STARTTLS choices, styled like the split/combined choice. Switching IMAP to STARTTLS asks first, because Home Assistant can't use it.
- Repair, Restart, Reset, Sign out, Remove and split/combined switching ask in a dialog with Proton's wording.

## 3.27.2-23

- Switching between split and combined addresses now says, like Proton's app, that the IMAP integration has to be set up again from scratch.

## 3.27.2-22

- Wording matches Proton's own Bridge app: Synchronizing, Mailbox details, Hostname, Split addresses, Show All Mail, Collect usage diagnostics, Check now.
- Clearer Repair and Reset descriptions, including what they mean for Home Assistant.

## 3.27.2-21

- Updated Debian trixie-slim base image (first run of the daily update check).

## 3.27.2-20

- Console: autofill, autocorrect and password-manager prompts are off on the command line.

## 3.27.2-19

- Copy buttons for the server and the IMAP and SMTP ports.

## 3.27.2-18

- SMTP is exposed on port 9025 for Home Assistant's SMTP integration, shown next to IMAP.

## 3.27.2-17

- Console: your own commands' output is shown in full.

## 3.27.2-16

- Console: the page's own info reads are hidden and secrets are masked.

## 3.27.2-15

- The page reloads by itself after an app update.

## 3.27.2-14

- Console: colours, without status polls or sync progress.

## 3.27.2-13

- Live raw console, the open tab is kept in the URL, and Bridge's own self-updates are off.

## 3.27.2-12

- Settings, privacy and layout polish.

## 3.27.2-11

- Shows a starting state instead of the sign-in form while Bridge loads.

## 3.27.2-10

- IMAP-over-SSL setting.

## 3.27.2-9

- Mail download progress, with the time-left estimate hidden until it has settled.

## 3.27.2-8

- Uses the authenticator app when Bridge offers a security key.

## 3.27.2-7

- Step-by-step sign-in, correct verification link and safer restarts.

## 3.27.2-6

- Recognises the prompt after a yes/no answer.

## 3.27.2-5

- Ignores the CLI's backspace redraws when reading its output.

## 3.27.2-4

- Read-only view of Bridge's recent output.

## 3.27.2-3

- Sign-in and settings web UI replaces the terminal.

## 3.27.2-2

- ttyd installed from its pinned upstream release.

## 3.27.2-1

- First release: Proton Mail Bridge 3.27.2 from proton.me, checksum-verified.
