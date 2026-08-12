import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.database import Base
from app.models.user import ChatConversation, ChatConversationSummary, ChatMessage
from app.services.context_builder import (
    ContextBudget,
    ContextBudgetExceededError,
    build_chat_context,
)
from app.services.token_estimator import token_upper_bound
from app.services.artifact_microcompact import MicrocompactPolicy
from app.services.conversation_summary_service import (
    _select_summary_prefix,
    compact_conversation_if_needed,
    should_summarize,
)


def _message(message_id, role, content, status="completed"):
    return SimpleNamespace(
        id=message_id,
        role=role,
        content=content,
        status=status,
    )


def _state(**overrides):
    state = {
        "current_page": "chat",
        "profile": {"allergies": ["花生严重过敏"]},
        "latest_plan": {"id": 7, "daily_calorie_target": 1800},
        "page_context": {},
        "risk_notice": "",
        "retrieved_knowledge": [],
        "citations": [],
    }
    state.update(overrides)
    return state


class ContextBuilderTests(unittest.TestCase):
    def test_estimator_is_a_safe_upper_bound_for_ascii_and_emoji(self):
        self.assertGreaterEqual(token_upper_bound("a" * 4000), 4000)
        self.assertGreaterEqual(token_upper_bound("😀" * 100), 400)

    def test_oversized_current_message_is_rejected_before_model_call(self):
        with self.assertRaises(ContextBudgetExceededError):
            build_chat_context(
                state=_state(profile={}, latest_plan=None),
                history=[],
                current_user_content="x" * 4000,
                current_user_message_id=1,
                budget=ContextBudget(2400, 200, 200),
            )

    def test_settings_reject_context_reserves_that_fill_the_window(self):
        with self.assertRaisesRegex(ValueError, "reserves"):
            Settings(
                _env_file=None,
                CHAT_CONTEXT_WINDOW_TOKENS=100,
                CHAT_CONTEXT_MAX_OUTPUT_TOKENS=80,
                CHAT_CONTEXT_SAFETY_BUFFER_TOKENS=20,
            )

    def test_settings_reject_invalid_microcompact_thresholds(self):
        with self.assertRaisesRegex(ValueError, "microcompact target"):
            Settings(
                _env_file=None,
                CHAT_MICROCOMPACT_FULL_ARTIFACT_TOKENS=100,
                CHAT_MICROCOMPACT_TARGET_ARTIFACT_TOKENS=100,
            )

    def test_build_is_within_budget_and_keeps_authoritative_profile(self):
        history = [
            _message(index, "user" if index % 2 else "assistant", "普通历史" * 30)
            for index in range(1, 21)
        ]
        result = build_chat_context(
            state=_state(),
            history=history,
            current_user_content="推荐今天的加餐",
            current_user_message_id=999,
            budget=ContextBudget(2400, 100, 100),
        )
        joined = "\n".join(str(message.content) for message in result.messages)
        self.assertIn("花生严重过敏", joined)
        self.assertTrue(result.diagnostics["within_budget"])
        self.assertLessEqual(
            result.diagnostics["estimated_input_tokens"],
            result.diagnostics["input_budget_tokens"],
        )
        self.assertGreater(result.diagnostics["history_dropped"], 0)

    def test_history_budget_never_splits_user_assistant_turn(self):
        history = [
            _message(1, "user", "第一轮用户" * 20),
            _message(2, "assistant", "第一轮助手" * 20),
            _message(3, "user", "第二轮用户" * 20),
            _message(4, "assistant", "第二轮助手" * 20),
        ]
        result = build_chat_context(
            state=_state(profile={}, latest_plan=None),
            history=history,
            current_user_content="继续",
            current_user_message_id=999,
            budget=ContextBudget(2000, 100, 80),
        )
        included = result.diagnostics["history_included_ids"]
        self.assertIn(included, [[], [3, 4], [1, 2, 3, 4]])

    def test_only_citations_for_included_knowledge_are_returned(self):
        knowledge = [
            {"title": "短资料", "content": "蛋白质建议"},
            {"title": "超长资料", "content": "很长的资料" * 500},
        ]
        result = build_chat_context(
            state=_state(retrieved_knowledge=knowledge),
            history=[],
            current_user_content="蛋白质怎么吃",
            current_user_message_id=1,
            budget=ContextBudget(2400, 100, 100),
            microcompact_policy=MicrocompactPolicy(
                full_content_tokens=50,
                compact_content_tokens=20,
            ),
        )
        included_indexes = [
            artifact["original_index"]
            for artifact in result.diagnostics["artifacts"]
            if artifact["mode"] != "dropped"
        ]
        self.assertEqual(result.included_citation_indexes, included_indexes)
        self.assertEqual(result.diagnostics["knowledge_retrieved"], 2)
        self.assertEqual(
            result.diagnostics["knowledge_included"], len(included_indexes)
        )

    def test_long_rag_artifact_is_microcompacted_with_trace_diagnostics(self):
        knowledge = [
            {
                "chunk_id": "risk-chunk-1",
                "title": "膝伤训练风险",
                "content": (
                    "普通背景。" * 100
                    + "膝盖疼痛时不应继续负重深蹲，每周训练次数需要下调。"
                ),
            }
        ]
        result = build_chat_context(
            state=_state(retrieved_knowledge=knowledge),
            history=[],
            current_user_content="膝盖疼怎么训练",
            current_user_message_id=1,
            budget=ContextBudget(4000, 100, 100),
            microcompact_policy=MicrocompactPolicy(
                full_content_tokens=60,
                compact_content_tokens=30,
            ),
        )
        joined = "\n".join(str(message.content) for message in result.messages)
        artifacts = result.diagnostics["artifacts"]
        self.assertIn("微压缩", joined)
        self.assertIn("膝盖疼痛", joined)
        self.assertEqual(artifacts[0]["reference_id"], "risk-chunk-1")
        self.assertEqual(artifacts[0]["mode"], "microcompact")
        self.assertGreater(result.diagnostics["artifact_tokens_saved"], 0)
        self.assertEqual(result.included_citation_indexes, [0])

    def test_completed_summary_is_injected_and_diagnosed(self):
        summary = SimpleNamespace(
            id=9,
            covered_through_message_id=20,
            summary_text="当前目标：十二周减重六公斤",
        )
        history = [
            _message(19, "user", "已经被摘要覆盖的旧消息"),
            _message(20, "assistant", "已经被摘要覆盖的旧回复"),
            _message(21, "user", "摘要游标之后的新消息"),
            _message(22, "assistant", "摘要游标之后的新回复"),
        ]
        result = build_chat_context(
            state=_state(),
            history=history,
            current_user_content="回顾目标",
            current_user_message_id=23,
            budget=ContextBudget(3500, 200, 200),
            summary=summary,
        )
        joined = "\n".join(str(message.content) for message in result.messages)
        self.assertIn("十二周减重六公斤", joined)
        self.assertEqual(result.diagnostics["summary_id"], 9)
        self.assertEqual(
            result.diagnostics["summary_covered_through_message_id"], 20
        )
        self.assertEqual(result.diagnostics["history_covered_by_summary"], 2)
        self.assertEqual(result.diagnostics["history_included_ids"], [21, 22])

    def test_current_message_is_not_duplicated_from_history(self):
        history = [_message(10, "user", "当前问题")]
        result = build_chat_context(
            state=_state(),
            history=history,
            current_user_content="当前问题",
            current_user_message_id=10,
            budget=ContextBudget(2000, 200, 200),
        )
        occurrences = sum(
            str(message.content) == "当前问题" for message in result.messages
        )
        self.assertEqual(occurrences, 1)


class SummarySelectionTests(unittest.TestCase):
    def test_trigger_supports_token_or_message_threshold(self):
        messages = [_message(1, "user", "消息" * 20)]
        self.assertTrue(
            should_summarize(messages, trigger_tokens=5, trigger_messages=40)
        )
        self.assertTrue(
            should_summarize(messages * 2, trigger_tokens=999, trigger_messages=2)
        )
        self.assertFalse(
            should_summarize(messages, trigger_tokens=999, trigger_messages=40)
        )

    def test_summary_prefix_does_not_split_user_assistant_pair(self):
        messages = [
            _message(1, "user", "旧用户" * 20),
            _message(2, "assistant", "旧助手" * 20),
            _message(3, "user", "近用户" * 20),
            _message(4, "assistant", "近助手" * 20),
        ]
        prefix = _select_summary_prefix(messages, keep_recent_tokens=25)
        self.assertEqual([message.id for message in prefix], [1, 2])


class _FakeSummaryLlm:
    def __init__(self, content):
        self.content = content

    async def ainvoke(self, _messages):
        return SimpleNamespace(content=self.content)


class ConversationSummaryPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "summary.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.session_factory() as session:
            conversation = ChatConversation(user_id=1, title="summary-test")
            session.add(conversation)
            await session.flush()
            self.conversation_id = conversation.id
            session.add_all(
                [
                    ChatMessage(
                        conversation_id=conversation.id,
                        role="user" if index % 2 else "assistant",
                        content=f"第{index}条消息：十二周减重六公斤并持续记录训练。",
                    )
                    for index in range(1, 9)
                ]
            )
            await session.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp_dir.cleanup()

    @staticmethod
    def _settings():
        return SimpleNamespace(
            LLM_MODEL="test-model",
            LLM_API_KEY="",
            LLM_BASE_URL="http://unused",
            CHAT_SUMMARY_MAX_OUTPUT_TOKENS=500,
            CHAT_CONTEXT_MAX_HISTORY_MESSAGES=500,
            CHAT_SUMMARY_TRIGGER_TOKENS=1,
            CHAT_SUMMARY_TRIGGER_MESSAGES=2,
            CHAT_SUMMARY_KEEP_RECENT_TOKENS=35,
        )

    async def test_success_persists_completed_summary_and_cursor(self):
        payload = {
            "current_goal": "十二周减重六公斤",
            "confirmed_facts": [],
            "constraints": [],
            "decisions": [],
            "open_questions": [],
            "pending_actions": ["持续记录训练"],
            "corrections": [],
        }
        with patch(
            "app.services.conversation_summary_service.async_session",
            self.session_factory,
        ), patch(
            "app.services.conversation_summary_service.get_settings",
            return_value=self._settings(),
        ), patch(
            "app.services.conversation_summary_service._summary_llm",
            return_value=_FakeSummaryLlm(json.dumps(payload, ensure_ascii=False)),
        ):
            created = await compact_conversation_if_needed(self.conversation_id)

        self.assertTrue(created)
        async with self.session_factory() as session:
            summaries = list(
                (
                    await session.execute(
                        select(ChatConversationSummary).where(
                            ChatConversationSummary.conversation_id
                            == self.conversation_id
                        )
                    )
                ).scalars()
            )
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].status, "completed")
        self.assertIn("十二周减重六公斤", summaries[0].summary_text)
        self.assertGreater(summaries[0].covered_through_message_id, 0)
        self.assertLess(summaries[0].covered_through_message_id, 8)

    async def test_invalid_model_output_records_failure_without_summary(self):
        with patch(
            "app.services.conversation_summary_service.async_session",
            self.session_factory,
        ), patch(
            "app.services.conversation_summary_service.get_settings",
            return_value=self._settings(),
        ), patch(
            "app.services.conversation_summary_service._summary_llm",
            return_value=_FakeSummaryLlm("not-json"),
        ):
            created = await compact_conversation_if_needed(self.conversation_id)

        self.assertFalse(created)
        async with self.session_factory() as session:
            summary = (
                await session.execute(select(ChatConversationSummary))
            ).scalar_one()
        self.assertEqual(summary.status, "failed")
        self.assertEqual(summary.error_type, "ValueError")
        self.assertEqual(summary.summary_text, "")
