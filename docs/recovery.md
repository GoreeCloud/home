# GoreeCloud Home Recovery and Portability

Home is recovery-sensitive because a household can accumulate device organization, capability mappings, scenes, automations, schedules and history that are difficult to reconstruct manually.

## Required protected state

As applicable and permitted by privacy policy:

- Home/room/floor/zone organization
- device registry and stable logical identities
- adapter mappings and non-secret configuration
- desired/reported state needed for continuity
- scenes and automations
- schedules and policy configuration
- automation execution history needed for recovery or diagnostics
- automation runtime cursor and schema ledger state needed to resume local event routing without treating historical events as new
- privacy-permitted history required for continuity

Reusable credentials, private keys and protocol secrets require an approved protected secret-recovery design and must not be copied into ordinary backups by convenience.

## Recovery qualification

Everkeep integration must eventually prove isolated restoration of an exact release and validate semantic device mappings, automation definitions, schedule duplicate-occurrence state, runtime cursor behavior, authorization boundaries and both Home/automation migration ledgers. A successful backup command alone is not recovery evidence.

Because dev.5 runtime delivery is ordered at-least-once rather than exact crash-deduplicated, recovery testing must also verify the documented replay boundary and must not introduce future non-idempotent automation actions without an approved idempotency/recovery design.

## Portability

Exports should preserve stable GoreeCloud capability identifiers and relationships so users can migrate Home configuration without being trapped by one protocol adapter or storage backend. Internal runtime cursor values are continuity state, not a portable user automation semantic, and should only be exported where an approved recovery format requires them.
