# Feature: Accounts: Shared Access or Users

**Priority:** 2 (decision needed)  
**Status:** TO DECIDE  
**Estimated Effort:** decision, then 2-5 days  

## Description

Decide how people log in to the UI and the API. The choice decides who may see
events and logs, so it comes before those APIs.

## Options

- **A. One shared access (today).** The Bearer token of `config.yaml`, typed in
  the browser and kept there. Simplest; everyone sees and can do everything; a
  leaked token is the whole lab.
- **B. Shared access, token kept server-side.** A login page; a small backend
  next to nginx holds the token and gives the browser a session cookie. The
  token never reaches the browser; still one role.
- **C. Users and an administrator.** Wi-Lab (or the frontend backend) knows
  users. A user sees and acts on their own reservations; the administrator also
  sees logs and other users' reservations, releases everything and runs the
  protected commands (today `protected_commands_password`). Needed if raw logs
  are shown and if teams share the lab. With users, the reservation ID stops
  being a secret: authorization comes from the login.

## Implementation Tasks

- [ ] Decide A, B or C
- [ ] B: session backend in the frontend container
- [ ] C: users, roles, login; reservations owned by a user; protected commands for the administrator

## Testing

- [ ] C: a user cannot see or change another user's reservation; the administrator can

## Benefits

- **Security:** Secrets out of the browser (B) or per-user access (C)

## Breaking Changes

- C changes how clients authenticate

## Success Criteria

- ✅ The decision is recorded and the chosen option implemented
