"""Durable dispatch before subprocess IO; stale fences can never publish a result."""

import hashlib
from time import monotonic
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from calorie_app.core.errors import DomainError
from calorie_app.integrations.gemini.protocol import ProviderOutcome
from calorie_app.integrations.gemini.transport import execute
from calorie_app.modules.ai import repository as ai_repo
from calorie_app.modules.ai.cleanup import sweep
from calorie_app.modules.ai.configuration import configuration
from calorie_app.modules.ai.food_analysis import proposal
from calorie_app.modules.ai.schemas import Proposal
from calorie_app.modules.ai.storage import PhotoStorage
from calorie_app.modules.jobs import repository as repo


class Runner:
    def __init__(self, engine, factory, settings, *, stop=None, hook=None, transport=None):
        self.engine, self.factory, self.settings = engine, factory, settings
        self.worker_token = uuid4()
        self.stop = stop or (lambda: False)
        self.hook = hook or (lambda boundary, claim: None)
        self.transport = transport or execute

    def _read_image(self, claimed):
        key = claimed["storage_key"]
        with self.engine.connect() as connection, Session(bind=connection) as session:
            lock = "e7-storage:" + key
            if not ai_repo.lock_session(session, lock):
                raise DomainError(503, "ai_storage_unavailable")
            try:
                descriptor = ai_repo.call(
                    session,
                    "SELECT app.e7_read_descriptor(:job,:fence)",
                    job=claimed["job_id"],
                    fence=claimed["fence"],
                )
                session.commit()
                if descriptor is None:
                    raise DomainError(410, "image_expired")
                raw = PhotoStorage(self.settings.ai_photo_root).read(key)
                if hashlib.sha256(raw).hexdigest() != descriptor["prepared_hash"]:
                    raise DomainError(410, "image_unavailable")
                return raw
            finally:
                session.rollback()
                ai_repo.unlock_session(session, lock)
                session.commit()

    def _finish(self, claimed, outcome, *, allow_retry=True, code_override=None):
        with self.factory() as session:
            if not ai_repo.call(
                session,
                "SELECT app.e7_finish_context(:job,:fence)",
                job=claimed["job_id"],
                fence=claimed["fence"],
            ):
                session.commit()
                return False
            value = None
            code = code_override or outcome.code
            retry = None
            if outcome.code == "ok" and outcome.result is not None:
                try:
                    value = Proposal.model_validate(
                        proposal(session, outcome.result, outcome.model_version)
                    ).model_dump(mode="json")
                except ValueError:
                    code = "provider_result_invalid"
            elif allow_retry and outcome.retry_kind == "minute" and not self.stop():
                code = "provider_minute_quota"
                retry = max(1, outcome.retry_after_seconds or 1)
            elif allow_retry and not outcome.sent and not self.stop():
                code = "provider_before_send"
                retry = 1
            result = ai_repo.call(
                session,
                "SELECT app.e7_finish(:job,:fence,CAST(:proposal AS jsonb),:code,:retry)",
                job=claimed["job_id"],
                fence=claimed["fence"],
                proposal=None if value is None else ai_repo.encoded(value),
                code=code,
                retry=retry,
            )
            session.commit()
            return result

    def process(self, job):
        fence = uuid4()
        with self.factory() as session:
            claimed = repo.claim(session, job, fence)
            session.commit()
        if claimed is None:
            return False
        self.hook("after_claim", claimed)
        try:
            cfg = configuration(self.settings)
            pinned = claimed["profile"]
            if cfg.reason is not None or any(
                pinned[key] != cfg.profile[key]
                for key in (
                    "provider",
                    "model",
                    "pool_scope",
                    "prompt_version",
                    "schema_version",
                    "preparation_version",
                    "rest_profile_version",
                )
            ):
                self._finish(
                    claimed,
                    ProviderOutcome("provider_unavailable", sent=False),
                    allow_retry=False,
                    code_override="ai_profile_unavailable",
                )
                return True
            image = self._read_image(claimed)
            kinds = (["count_tokens"] if not claimed["preflight_done"] else []) + ["generate"]
            for kind in kinds:
                if self.stop():
                    return True  # No new dispatch; safe claimed phase can be reclaimed.
                self.hook("before_dispatch", claimed)
                attempt = uuid4()
                marker_time = monotonic()
                with self.factory() as session:
                    if not ai_repo.pool_available(session, cfg.profile, cfg.limits):
                        session.rollback()
                        self._finish(
                            claimed,
                            ProviderOutcome("provider_unavailable", sent=False),
                            allow_retry=False,
                            code_override="ai_pool_or_restore_unavailable",
                        )
                        return True
                    dispatched = repo.dispatch(
                        session, job, fence, kind, attempt, self.worker_token
                    )
                    session.commit()
                if dispatched is None or "error" in dispatched:
                    return True
                self.hook("after_dispatch", claimed)
                timeout = float(dispatched["timeout_seconds"]) - (monotonic() - marker_time)
                if timeout <= 0 or self.stop():
                    # A durable qualification remains unknown after a crash.
                    outcome = ProviderOutcome("provider_result_unknown")
                else:
                    transport_cfg = {**cfg.transport, **pinned}
                    outcome = self.transport(
                        pinned["provider"],
                        "countTokens" if kind == "count_tokens" else "generateContent",
                        image,
                        transport_cfg,
                        timeout,
                    )
                self.hook("after_response", claimed)
                # execute confirms physical termination, including hard timeout.
                with self.factory() as session:
                    repo.physical_finish(session, attempt, self.worker_token, outcome)
                    session.commit()
                if kind == "count_tokens" and outcome.code == "ok":
                    with self.factory() as session:
                        ok = ai_repo.call(
                            session,
                            "SELECT app.e7_preflight_finish(:job,:fence,:tokens)",
                            job=job,
                            fence=fence,
                            tokens=outcome.token_count,
                        )
                        session.commit()
                    if not ok:
                        return True
                else:
                    self.hook("before_result_commit", claimed)
                    self._finish(claimed, outcome, allow_retry=kind == "generate")
                    return True
        except DomainError as error:
            self._finish(
                claimed,
                ProviderOutcome("provider_unavailable", sent=False),
                allow_retry=False,
                code_override=error.code,
            )
            if error.code in {"image_expired", "image_unavailable"}:
                return True
        except SQLAlchemyError:
            # The durable marker/fence decides recovery; never resend in this process.
            return True
        return True

    def cycle(self, batch=100):
        if not 1 <= batch <= 1000:
            raise ValueError("invalid worker batch")
        with self.factory() as session:
            jobs = repo.candidates(session, batch)
        handled = 0
        for job in jobs:
            if self.stop():
                break
            handled += bool(self.process(job))
        sweep(self.engine, self.factory, self.settings.ai_photo_root, batch)
        return handled
