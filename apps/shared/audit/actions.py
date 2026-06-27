class AuditAction:
    """
    계층 A 사용자 행동 타입.

    값은 "{resource}.{verb}" 형태의 문자열로 DB에 그대로 저장한다.
    resource는 파일명이 아니라 감사 대상 비즈니스 리소스 기준으로 정한다.
    """

    # 인증: 로그인 전이라 데코레이터 대신 auth 엔드포인트에서 직접 기록한다.
    USER_SIGNUP = "user.signup"
    USER_SIGNUP_FAILED = "user.signup_failed"
    USER_LOGIN = "user.login"
    USER_LOGIN_FAILED = "user.login_failed"
    USER_LOGOUT = "user.logout"
    AUTH_PERMISSION_DENIED = "auth.permission_denied"

    PERMISSION_GRANT = "permission.grant"
    PERMISSION_REVOKE = "permission.revoke"
    PERMISSION_DENIED = "permission.denied"

    # 앱/워크플로우/배포: 사용자가 워크플로우 운영 단위에서 수행한 행동.
    APP_CREATE = "app.create"
    APP_UPDATE = "app.update"
    APP_CLONE = "app.clone"
    APP_DELETE = "app.delete"

    WORKFLOW_CREATE = "workflow.create"
    WORKFLOW_UPDATE = "workflow.update"
    WORKFLOW_DEPLOY = "workflow.deploy"
    WORKFLOW_EXECUTE = "workflow.execute"

    DEPLOYMENT_TOGGLE = "deployment.toggle"
    DEPLOYMENT_DELETE = "deployment.delete"

    # 외부 연결 및 LLM 자격증명.
    CONNECTION_CREATE = "connection.create"

    CREDENTIAL_CREATE = "credential.create"
    CREDENTIAL_DELETE = "credential.delete"

    MODEL_PRICING_UPDATE = "model.pricing_update"
    LLM_CALL = "llm.call"

    # 지식베이스와 문서 수명주기.
    KNOWLEDGE_CREATE = "knowledge.create"
    KNOWLEDGE_UPDATE = "knowledge.update"
    KNOWLEDGE_DELETE = "knowledge.delete"

    DOCUMENT_UPLOAD = "document.upload"
    DOCUMENT_PROCESS = "document.process"
    DOCUMENT_DELETE = "document.delete"
