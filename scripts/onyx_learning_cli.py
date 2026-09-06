"""Machine-readable owner CLI for Onyx onboarding and learning controls."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.continuous_learning_v1 import (  # noqa: E402
    AuthorizedHybridRankerV1,
    ContinuousLearningV1ContractError,
    ContinuousLearningV1Denied,
    HybridDocumentV1,
    OnyxContinuousLearningV1,
    OnyxOwnerInterviewV1,
    QUESTIONS,
)
from core.governed_personalization_v1 import (  # noqa: E402
    GovernedPersonalizationContractError,
    GovernedPersonalizationDenied,
    GovernedPersonalizationError,
    GovernedPersonalizationStoreV1,
    PersonalizationFeatureGateV1,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="onyx-learning")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--workspace", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("questions")
    answer = commands.add_parser("answer")
    answer.add_argument("question_id")
    answer.add_argument("value")
    observe = commands.add_parser("observe")
    observe.add_argument("text")
    commands.add_parser("prompt")
    rank = commands.add_parser("rank")
    rank.add_argument("query")
    rank.add_argument("--document", action="append", required=True)
    rank.add_argument("--limit", type=int, default=8)
    return parser


def _payload(value: object) -> object:
    if hasattr(value, "payload"):
        return value.payload()  # type: ignore[union-attr]
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, tuple):
        return [_payload(item) for item in value]
    return value


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = GovernedPersonalizationStoreV1(
            args.database,
            owner_profile_id=args.owner,
            workspace_id=args.workspace,
            gate=PersonalizationFeatureGateV1(True, False),
        )
        interview = OnyxOwnerInterviewV1(store)
        if args.command == "status":
            result: object = interview.status()
        elif args.command == "questions":
            result = QUESTIONS
        elif args.command == "answer":
            result = interview.answer(args.question_id, args.value)
        elif args.command == "observe":
            result = OnyxContinuousLearningV1(store).observe_turn(args.text)
        elif args.command == "prompt":
            result = {"instruction": interview.prompt_instruction()}
        else:
            documents = []
            for index, raw in enumerate(args.document):
                try:
                    identifier, content = raw.split("=", 1)
                except ValueError as exc:
                    raise ContinuousLearningV1ContractError(
                        "documents must use id=text"
                    ) from exc
                documents.append(HybridDocumentV1(identifier, content))
            result = AuthorizedHybridRankerV1().rank(
                args.query, documents, limit=args.limit
            )
        print(json.dumps({"ok": True, "result": _payload(result)}, ensure_ascii=False, sort_keys=True))
        return 0
    except (
        ContinuousLearningV1ContractError,
        ContinuousLearningV1Denied,
        GovernedPersonalizationContractError,
        GovernedPersonalizationDenied,
        GovernedPersonalizationError,
    ) as exc:
        print(
            json.dumps(
                {"ok": False, "error": {"code": type(exc).__name__, "message": str(exc)}},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

