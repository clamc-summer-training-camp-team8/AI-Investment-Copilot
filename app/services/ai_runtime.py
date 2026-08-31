"""Agent Runtime 运行轨迹与模型成本的 SQL 持久化实现。"""

from __future__ import annotations

from sqlalchemy import delete

from app.ai.integration import to_backend_envelope
from app.ai.runtime import RuntimeExecution
from app.db.models.ai import AiRun, ModelCallLog


class SqlRuntimeRecorder:
    """每个检查点独立提交，使 worker 异常退出后仍可诊断最后状态。"""

    def started(self, execution: RuntimeExecution) -> None:
        self._save(execution, include_calls=False)

    def checkpoint(self, execution: RuntimeExecution) -> None:
        self._save(execution, include_calls=False)

    def finished(self, execution: RuntimeExecution) -> None:
        self._save(execution, include_calls=True)

    @staticmethod
    def _save(execution: RuntimeExecution, *, include_calls: bool) -> None:
        from app.db.session import session_scope

        envelope = to_backend_envelope(execution)
        with session_scope() as session:
            row = session.get(AiRun, execution.run_id)
            if row is None:
                row = AiRun(
                    run_id=execution.run_id,
                    task=execution.task,
                    status=execution.status,
                    started_at=execution.started_at,
                )
                session.add(row)
            row.task = execution.task
            row.status = execution.status
            row.idempotency_key = execution.idempotency_key
            row.attempt = execution.attempt
            row.retryable = execution.retryable
            row.started_at = execution.started_at
            row.finished_at = execution.finished_at
            row.model_version = execution.model_version
            row.prompt_version = execution.prompt_version
            row.retrieval_versions = list(execution.retrieval_versions)
            row.schema_name = execution.schema_name
            row.degraded_reason = execution.degraded_reason
            row.errors = list(execution.errors)
            row.transitions = envelope["transitions"]
            row.result = envelope["candidate_result"]
            row.verification = envelope["verification"]
            session.flush()
            if include_calls:
                session.execute(delete(ModelCallLog).where(ModelCallLog.run_id == execution.run_id))
                for call in execution.model_calls:
                    session.add(
                        ModelCallLog(
                            run_id=execution.run_id,
                            provider=call.provider,
                            model_version=call.model_version,
                            request_id=call.request_id,
                            prompt_version=call.prompt_version,
                            input_tokens=call.input_tokens,
                            output_tokens=call.output_tokens,
                            total_tokens=call.total_tokens,
                            latency_ms=call.latency_ms,
                            attempt_count=call.attempt_count,
                            cost_amount=call.cost_amount,
                            currency=call.currency,
                            success=call.success,
                            error_code=call.error_code,
                        )
                    )
