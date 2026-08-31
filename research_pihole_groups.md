# Pi-hole group and client references

## Official API documentation
- https://docs.pi-hole.net/api/

## Official database documentation
- https://docs.pi-hole.net/database/domain-database/groups/
- https://docs.pi-hole.net/database/query-database/

## Key findings
- Pi-hole group management supports assigning clients to groups; the default group is special and applies to domains and clients not assigned to another group.
- Device-level targeting should use Pi-hole client identities such as IP addresses, hostnames, or MAC-based client records, and those identities must be assigned to the intended group.
- A YouTube block should be implemented as a dedicated domain/adlist policy assigned to a YouTube-block group, rather than globally enabling/disabling all Pi-hole blocking.
- Exact API/database operations should be confirmed against the server's installed Pi-hole version before deployment.

## Search result sources also reviewed
- https://discourse.pi-hole.net/t/assign-a-list-of-clients-to-groups/54044
- https://discourse.pi-hole.net/t/how-to-dis-enable-group-specific-lists-or-list-entries-via-api/42292
