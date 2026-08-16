variable "REGISTRY" {}
variable "RELEASE_SHA" {}
variable "PRODUCTION_API_URL" {}
variable "ACCOUNT_CENTER_URL" {}

target "web-runtime" {
  context    = "./web"
  dockerfile = "Dockerfile"
  target     = "runtime"
  platforms  = ["linux/amd64"]
  args = {
    RELEASE_SHA                   = RELEASE_SHA
    NEXT_PUBLIC_API_URL           = PRODUCTION_API_URL
    NEXT_PUBLIC_ACCOUNT_CENTER_URL = ACCOUNT_CENTER_URL
  }
  output = ["type=registry,name=${REGISTRY}/sanchezcloud-scholens-web,push-by-digest=true,name-canonical=true"]
  attest = ["type=provenance,mode=max", "type=sbom"]
}

target "web-source-maps" {
  context    = "./web"
  dockerfile = "Dockerfile"
  target     = "source-maps"
  platforms  = ["linux/amd64"]
  args = {
    RELEASE_SHA                   = RELEASE_SHA
    NEXT_PUBLIC_API_URL           = PRODUCTION_API_URL
    NEXT_PUBLIC_ACCOUNT_CENTER_URL = ACCOUNT_CENTER_URL
  }
  output = ["type=local,dest=web-source-maps"]
}

group "default" {
  targets = ["web-runtime", "web-source-maps"]
}
