# Permissions and service addresses

This repository contains no account IDs, project IDs, endpoints, API keys, or
registry credentials. Replace every `CHANGE_ME_*` value in
`config/deployment.env.example` with values from the target Huawei Cloud public
cloud project.

## Identities

Two authorization layers are required:

1. **Deployment operator** — the IAM user or federated principal that creates
   and manages the ModelArts service. Start with the system-defined
   `ModelArtsXInferAllPolicy`, or review `iam/operator-policy.json` with your IAM
   administrator for a narrower identity policy.
2. **ModelArts agency** — the agency assumed by ModelArts to pull the private
   SWR image, inspect the dedicated resource pool, and mount SFS Turbo. Review
   `iam/modelarts-agency-policy.json` before assigning it. Remove the LTS actions
   only if LTS integration is disabled.

The exact minimum create-service action is `modelarts:service:create` with the
`modelarts:workspace:get` dependency. API key management additionally needs
`modelarts:apikey:list`, `create`, `bind`, `unbind`, and `delete`.

Official references:

- ModelArts inference actions: <https://support.huaweicloud.com/intl/en-us/api-modelarts/modelarts_03_0174.html>
- ModelArts agencies and dependency permissions: <https://support.huaweicloud.com/intl/en-us/permission-modelarts/modelarts_24_0081.html>
- SWR image permissions: <https://support.huaweicloud.com/intl/en-us/usermanual-swr/swr_01_0015.html>
- API key authentication: <https://support.huaweicloud.com/intl/en-us/inference-modelarts/inference2.0-modelarts-0008.html>

## Addresses to collect

| Value | Where to obtain it | Example format only |
|---|---|---|
| ModelArts endpoint | Huawei Cloud **Regions and Endpoints** for the selected region | `https://modelarts.<region>.myhuaweicloud.com` |
| Project ID | IAM console or `GET /v3/projects` | 32-character project ID |
| Workspace ID | ModelArts workspace details; use `0` for the default workspace | `0` |
| Resource pool ID | ModelArts dedicated resource pool details or `GET /v2/{project_id}/pools` | `pool-...` |
| A2 flavor ID | ModelArts deployment page in the target pool | Region-specific flavor ID |
| SFS Turbo ID | SFS Turbo file-system details | UUID-like ID |
| SWR image URI | SWR image details after mirroring | `swr.<region>.myhuaweicloud.com/org/repo:tag` |
| Inference call URL | ModelArts service **Basic Information > Call Info** after deployment | URL ending before `/v1` |

Never derive a production endpoint by guesswork. Copy the endpoint and call URL
from the target Huawei Cloud region. The control-plane create-service URI is:

```text
POST {MODELARTS_ENDPOINT}/v2/{PROJECT_ID}/services
```

The request header is `X-Auth-Token` with a short-lived IAM token. Inference
calls configured for API key authentication use:

```http
Authorization: Bearer <API_KEY_CONTENT>
```

Do not place either token in an environment file, Git commit, shell history, or
support ticket.

