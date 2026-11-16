# Public RDS trust bundle

`aws-rds-global-bundle.pem` is the public Amazon RDS CA certificate bundle from
<https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem>, linked by the
[RDS TLS documentation](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html).
It contains certificates only, with no private keys or application credentials.

This retained artifact has the same 108 certificates and exact SHA-256 that the
API image already required:

```text
e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3
```

The original bytes were retained in the existing Scholight repository's public
`global-bundle.pem`; they match the Scholens image's pre-existing checksum.
Vendoring makes that approved input reproducible. The upstream URL is mutable:
on 2026-11-16 it supplied a different 114-certificate bundle, which correctly
failed the existing checksum check. This change deliberately retains the prior
trust set instead of accepting that newer bundle or weakening verification.

The API Dockerfile copies this artifact and still checks the pinned SHA-256
before installing it at `/etc/ssl/certs/global-bundle.pem`. TLS verification and
runtime certificate selection remain unchanged. Updating the certificate set or
checksum requires a separate trust review; do not refresh it as a routine build
repair. Keep provenance, the artifact and its checksum test together.
