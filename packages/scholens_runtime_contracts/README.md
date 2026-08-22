# Scholens runtime contracts

`scholens_runtime_contracts` validates and composes managed database and cache
endpoints before Server or Jobs create a client. It is intentionally independent
of AWS SDKs and application frameworks so every runtime unit enforces the same
TLS, credential, hostname, port, and URL-structure rules.

Production cache endpoints must use `rediss`, include a non-empty username and
password, and resolve under the AWS ElastiCache DNS suffix. Production database
hosts must resolve under the AWS RDS DNS suffix. Development may use ordinary
DNS names or IP addresses, but still rejects URL delimiters, whitespace, and
invalid ports.

Internal Jobs callback bases are also validated here. Production requires an
explicit HTTP(S) authority and rejects loopback or non-routable hosts,
credentials, paths, queries, and fragments; development may use an explicitly
supplied loopback fallback.
