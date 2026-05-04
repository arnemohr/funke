"""Domain models for Funke Event Management System."""

from .admin import (
    AdminRole,
    AdminUser,
    CrewRole,
    Invitation,
    InvitationCreate,
    Organization,
)
from .bar_item import (
    BarItem,
    BarItemCategory,
    BarItemCreate,
    BarItemPatch,
    BarItemResponse,
    BarItemStockChange,
    ConsumptionResult,
    StockAdjustmentRequest,
)
from .event import (
    Event,
    EventCreate,
    EventPublic,
    EventStatus,
    EventUpdate,
)
from .fahrbericht import (
    ComputedTotals,
    CrewRef,
    Fahrbericht,
    FahrberichtPatch,
    FahrberichtResponse,
    FahrberichtStatus,
    SubmitResult,
)
from .fahrbericht import ExpenseLine as FahrberichtExpenseLine
from .lottery import LotteryResult, LotteryRun
from .message import (
    CustomMessageRequest,
    Message,
    MessageCreate,
    MessageDirection,
    MessageStatus,
    MessageType,
)
from .registration import (
    Registration,
    RegistrationAdminPatch,
    RegistrationCreate,
    RegistrationResponse,
    RegistrationStatus,
    RegistrationUpdate,
)
from .report import (
    EmailStatus,
    LineItem,
    ReportMeta,
    ReportResponse,
    ReportTotals,
    ReportVersion,
)
from .ship_state import (
    Co2Level,
    KloLevel,
    Note,
    NoteInput,
    PersennigStatus,
    ShipState,
    ShipStatePatch,
    ShipStatusSnapshot,
    Todo,
    TodoInput,
)

__all__ = [
    # Admin
    "AdminRole",
    "AdminUser",
    "CrewRole",
    "Invitation",
    "InvitationCreate",
    "Organization",
    # Event
    "Event",
    "EventCreate",
    "EventPublic",
    "EventStatus",
    "EventUpdate",
    # Lottery
    "LotteryResult",
    "LotteryRun",
    # Message
    "CustomMessageRequest",
    "Message",
    "MessageCreate",
    "MessageDirection",
    "MessageStatus",
    "MessageType",
    # Registration
    "Registration",
    "RegistrationAdminPatch",
    "RegistrationCreate",
    "RegistrationResponse",
    "RegistrationStatus",
    "RegistrationUpdate",
    # Bar + Ship (spec 011)
    "BarItem",
    "BarItemCategory",
    "BarItemCreate",
    "BarItemPatch",
    "BarItemResponse",
    "BarItemStockChange",
    "ConsumptionResult",
    "StockAdjustmentRequest",
    "Co2Level",
    "KloLevel",
    "Note",
    "NoteInput",
    "PersennigStatus",
    "ShipState",
    "ShipStatePatch",
    "ShipStatusSnapshot",
    "Todo",
    "TodoInput",
    # Fahrbericht (specs 012 + 014)
    "ComputedTotals",
    "CrewRef",
    "Fahrbericht",
    "FahrberichtPatch",
    "FahrberichtResponse",
    "FahrberichtStatus",
    "FahrberichtExpenseLine",
    "SubmitResult",
    # Report (spec 013)
    "EmailStatus",
    "LineItem",
    "ReportMeta",
    "ReportResponse",
    "ReportTotals",
    "ReportVersion",
]
