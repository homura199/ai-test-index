"""Read-only discovery of the project's existing SCF integration.

Never print credentials, environment variables, code, or signed download URLs.
"""
import json
import os

from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.scf.v20180416 import models, scf_client


def main():
    client = scf_client.ScfClient(
        credential.EnvironmentVariableCredential().get_credential(),
        os.environ.get("TENCENTCLOUD_REGION", "ap-guangzhou"),
    )
    request = models.ListFunctionsRequest()
    request.from_json_string(json.dumps({"Namespace": "default", "Limit": 100}))
    response = client.ListFunctions(request)
    output = []
    for fn in response.Functions or []:
        detail_request = models.GetFunctionRequest()
        detail_request.from_json_string(json.dumps({
            "FunctionName": fn.FunctionName, "Namespace": "default",
            "ShowCode": "FALSE",
        }))
        detail = client.GetFunction(detail_request)
        output.append({
            "name": fn.FunctionName,
            "type": detail.Type,
            "runtime": detail.Runtime,
            "handler": detail.Handler,
            "role": detail.Role,
            "timeout": detail.Timeout,
            "status": detail.Status,
            "trigger_types": [t.Type for t in (detail.Triggers or [])],
        })
    print(json.dumps({"region": client.region, "total": response.TotalCount, "functions": output}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except TencentCloudSDKException as exc:
        print(json.dumps({"error_code": exc.get_code(), "message": "SCF inspection failed; no secrets or source were logged."}))
        raise SystemExit(1)
