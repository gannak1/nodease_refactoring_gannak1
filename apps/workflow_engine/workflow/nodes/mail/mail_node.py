"""Mail 노드 - IMAP 기반 이메일 검색"""

import email
import imaplib
import socket
import ssl
import uuid
from datetime import datetime
from email.header import decode_header
from typing import Any, Dict, List, Optional

from jinja2 import Environment

from apps.workflow_engine.workflow.nodes.base.node import Node
from apps.workflow_engine.workflow.nodes.mail.entities import MailNodeData
from apps.shared.db.session import SessionLocal
from apps.workflow_engine.services.mail_credential_service import (
    MailCredentialResolver,
    ResolvedMailCredential,
)

_jinja_env = Environment(autoescape=False)


def _imap_quoted_string(value: str) -> str:
    if any(character in value for character in ("\r", "\n", "\x00")):
        raise RuntimeError("mail.search_criteria_invalid")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class _PinnedIMAP4(imaplib.IMAP4):
    def __init__(self, host: str, port: int, resolved_ip: str):
        self._resolved_ip = resolved_ip
        super().__init__(host=host, port=port)

    def _create_socket(self, timeout):
        return socket.create_connection((self._resolved_ip, self.port), timeout)


class _PinnedIMAP4SSL(imaplib.IMAP4_SSL):
    def __init__(self, host: str, port: int, resolved_ip: str):
        self._resolved_ip = resolved_ip
        super().__init__(host=host, port=port)

    def _create_socket(self, timeout):
        raw_socket = socket.create_connection((self._resolved_ip, self.port), timeout)
        return self.ssl_context.wrap_socket(raw_socket, server_hostname=self.host)


def _get_nested_value(data: Any, keys: List[str]) -> Any:
    """중첩된 딕셔너리에서 키 경로를 따라 값을 추출합니다."""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key)
        else:
            return None
    return data


class MailNode(Node[MailNodeData]):
    """
    IMAP을 사용하여 이메일을 검색하는 노드입니다.
    IMAP을 지원하는 모든 이메일 서비스에서 작동합니다.
    """

    node_type = "mailNode"

    def _run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        이메일 검색을 실행하고 결과를 반환합니다.

        [GEVENT] 동기 메서드로 변환 - gevent pool 호환성을 위해.
        IMAP 라이브러리는 이미 동기식이므로 _run_sync를 직접 호출합니다.
        """
        return self._run_sync(inputs)

    def _run_sync(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        이메일 검색 동기 로직 (run_in_executor에서 호출됨).
        """
        data = self.data
        if data.credential_id is None:
            raise RuntimeError("mail.credential_reference_required")

        # 변수 치환
        keyword = self._render_template(data.keyword or "", inputs)
        sender = self._render_template(data.sender or "", inputs)
        subject = self._render_template(data.subject or "", inputs)
        user_id = self._required_execution_subject_uuid()
        organization_id = self._required_context_uuid("organization_id")
        db, should_close = self._borrow_db_session()
        try:
            credential = MailCredentialResolver.resolve(
                db,
                user_id=user_id,
                organization_id=organization_id,
                credential_id=data.credential_id,
            )
        finally:
            if should_close:
                db.close()

        # IMAP 연결
        mail = self._connect_imap(credential)

        try:
            # 폴더 선택
            status, _ = mail.select(data.folder)
            if status != "OK":
                raise RuntimeError("mail.folder_select_failed")

            # 검색 쿼리 구성
            search_query = self._build_search_query(keyword, sender, subject)

            # 검색 실행
            status, messages = mail.search(None, search_query)
            if status != "OK":
                raise RuntimeError("mail.search_failed")

            email_ids = messages[0].split()

            # 결과 제한 (기본값: 5)
            max_results = data.max_results if data.max_results is not None else 5
            email_ids = email_ids[-max_results:]

            # 각 이메일 가져오기 (최신 순)
            emails = []
            for email_id in reversed(email_ids):
                msg = self._fetch_email(mail, email_id)
                emails.append(msg)

            return {
                "emails": emails,
                "total_count": len(emails),
                "folder": data.folder,
            }

        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError("mail.operation_failed") from exc
        finally:
            # 연결 종료
            try:
                mail.close()
            except Exception:
                pass
            try:
                mail.logout()
            except Exception:
                pass

    def _connect_imap(self, credential: ResolvedMailCredential) -> imaplib.IMAP4:
        """IMAP 서버에 연결합니다."""
        mail: imaplib.IMAP4 | None = None
        try:
            if credential.use_ssl:
                mail = _PinnedIMAP4SSL(
                    credential.imap_host,
                    credential.imap_port,
                    credential.resolved_ip,
                )
            else:
                mail = _PinnedIMAP4(
                    credential.imap_host,
                    credential.imap_port,
                    credential.resolved_ip,
                )
                mail.starttls(ssl_context=ssl.create_default_context())

            mail.login(credential.email_address, credential.secret)
            return mail

        except imaplib.IMAP4.error as exc:
            self._shutdown_failed_connection(mail)
            raise RuntimeError("mail.authentication_failed") from exc
        except Exception as exc:
            self._shutdown_failed_connection(mail)
            raise RuntimeError("mail.connection_failed") from exc

    @staticmethod
    def _shutdown_failed_connection(mail: imaplib.IMAP4 | None) -> None:
        if mail is None:
            return
        try:
            mail.shutdown()
        except Exception:
            pass

    def _required_context_uuid(self, key: str) -> uuid.UUID:
        value = self.execution_context.get(key)
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"mail.{key}_required") from exc

    def _required_execution_subject_uuid(self) -> uuid.UUID:
        subject = self.execution_context.get("execution_subject")
        if not isinstance(subject, dict):
            raise RuntimeError("mail.execution_subject_required")
        subject_type = subject.get("subject_type") or subject.get("type") or "user"
        subject_id = subject.get("subject_id") or subject.get("id")
        if subject_type != "user":
            raise RuntimeError("mail.execution_subject_required")
        try:
            return uuid.UUID(str(subject_id))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("mail.execution_subject_required") from exc

    def _borrow_db_session(self):
        session_factory = self.execution_context.get("db_session_factory")
        if callable(session_factory):
            return session_factory(), True
        legacy_session = self.execution_context.get("db")
        if legacy_session is not None:
            return legacy_session, False
        return SessionLocal(), True

    def _build_search_query(self, keyword: str, sender: str, subject: str) -> str:
        """IMAP 검색 쿼리를 구성합니다."""
        criteria = []

        if self.data.unread_only:
            criteria.append("UNSEEN")

        if keyword:
            criteria.append(f"TEXT {_imap_quoted_string(keyword)}")

        if sender:
            criteria.append(f"FROM {_imap_quoted_string(sender)}")

        if subject:
            criteria.append(f"SUBJECT {_imap_quoted_string(subject)}")

        # 날짜 필터: start_date가 없으면 기본 7일 전으로 설정
        start_date = self.data.start_date
        if not start_date:
            # 7일 전 날짜 계산
            from datetime import timedelta

            seven_days_ago = datetime.now() - timedelta(days=7)
            start_date = seven_days_ago.strftime("%Y-%m-%d")

        if start_date:
            # IMAP 날짜 형식: DD-Mon-YYYY
            try:
                date_obj = datetime.strptime(start_date, "%Y-%m-%d")
                imap_date = date_obj.strftime("%d-%b-%Y")
                criteria.append(f"SINCE {imap_date}")
            except ValueError:
                raise RuntimeError("mail.search_criteria_invalid") from None

        if self.data.end_date:
            try:
                date_obj = datetime.strptime(self.data.end_date, "%Y-%m-%d")
                # BEFORE criteria excludes the date, so we add 1 day to include it
                from datetime import timedelta

                date_obj += timedelta(days=1)

                imap_date = date_obj.strftime("%d-%b-%Y")
                criteria.append(f"BEFORE {imap_date}")
            except ValueError:
                raise RuntimeError("mail.search_criteria_invalid") from None

        return " ".join(criteria) if criteria else "ALL"

    def _fetch_email(self, mail: imaplib.IMAP4_SSL, email_id: bytes) -> Dict[str, Any]:
        """이메일 상세 정보를 가져옵니다."""
        status, msg_data = mail.fetch(email_id, "(RFC822)")

        if status != "OK" or not msg_data or not msg_data[0]:
            return {
                "id": email_id.decode(),
                "error": "Failed to fetch email",
            }

        msg = email.message_from_bytes(msg_data[0][1])

        # 헤더 파싱
        subject = self._decode_header(msg.get("Subject", ""))
        from_ = self._decode_header(msg.get("From", ""))
        to = self._decode_header(msg.get("To", ""))
        date = msg.get("Date", "")

        # 본문 추출
        body_text = ""
        body_html = ""
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                if "attachment" in content_disposition:
                    # 첨부파일
                    filename = part.get_filename()
                    if filename:
                        attachments.append(
                            {
                                "filename": self._decode_header(filename),
                                "content_type": content_type,
                                "size": len(part.get_payload(decode=True) or b""),
                            }
                        )
                elif content_type == "text/plain" and not body_text:
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body_text = payload.decode("utf-8", errors="ignore")
                    except Exception:
                        pass
                elif content_type == "text/html" and not body_html:
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body_html = payload.decode("utf-8", errors="ignore")
                    except Exception:
                        pass
        else:
            # 단일 파트 메시지
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    body_text = payload.decode("utf-8", errors="ignore")
            except Exception:
                pass

        # Mark as read if requested
        if self.data.mark_as_read:
            try:
                mail.store(email_id, "+FLAGS", "\\Seen")
            except Exception:
                pass

        return {
            "id": email_id.decode(),
            "subject": subject,
            "from": from_,
            "to": to,
            "date": date,
            "body_text": body_text[:1000] if body_text else "",  # 처음 1000자
            "body_html": body_html[:1000] if body_html else "",
            "snippet": body_text[:200] if body_text else "",  # 미리보기
            "has_attachments": len(attachments) > 0,
            "attachments": attachments,
        }

    def _decode_header(self, header: str) -> str:
        """이메일 헤더를 디코딩합니다."""
        if not header:
            return ""

        try:
            decoded_parts = decode_header(header)
            result = []
            for content, encoding in decoded_parts:
                if isinstance(content, bytes):
                    result.append(content.decode(encoding or "utf-8", errors="ignore"))
                else:
                    result.append(str(content))
            return "".join(result)
        except Exception:
            return str(header)

    def _render_template(self, template: Optional[str], inputs: Dict[str, Any]) -> str:
        """
        템플릿을 Jinja2로 렌더링합니다.
        referenced_variables의 value_selector를 사용하여 이전 노드의 output에서 값을 추출합니다.
        """
        if not template:
            return ""

        context: Dict[str, Any] = {}

        # referenced_variables에서 각 변수의 값을 추출
        for variable in self.data.referenced_variables:
            var_name = variable.name
            selector = variable.value_selector

            # 필수값 체크
            if not var_name or not selector or len(selector) < 1:
                context[var_name] = ""
                continue

            target_node_id = selector[0]

            # 입력 데이터에서 해당 노드의 결과 찾기
            source_data = inputs.get(target_node_id)

            if source_data is None:
                context[var_name] = ""
                continue

            # 값 추출 (selector가 2개 이상일 경우 중첩된 값 탐색)
            if len(selector) > 1:
                value = _get_nested_value(source_data, selector[1:])
                context[var_name] = value if value is not None else ""
            else:
                # selector가 노드 ID만 있는 경우
                context[var_name] = source_data

        # Jinja2 템플릿 렌더링
        try:
            return _jinja_env.from_string(template).render(**context)
        except Exception as e:
            raise ValueError(f"템플릿 렌더링 실패: {e}")
