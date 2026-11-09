from app.models.user import User
from app.models.email_verification import EmailVerificationCode
from app.models.course import Course, CourseMaterial, KnowledgePoint, MaterialParseJob
from app.models.profile import StudentProfile, MasteryRecord, WrongQuestion, ReviewPlan
from app.models.practice import PracticeRecord
from app.models.interview import InterviewRecord
from app.models.classroom import (
    Classroom, ClassMember, CourseEnrollment, CourseCollaborator, CourseShare,
)
from app.models.conversation import Conversation, ChatMessage
from app.models.knowledge_draft import KnowledgeDraft
from app.models.interview_assignment import InterviewAssignment
from app.models.assignment import Assignment, Submission
from app.models.question import Question, QuestionDraft
from app.models.exam import (
    Exam, ExamPlanDraft, ExamQuestion, ExamRecord, ExamSession,
)
from app.models.upload_event import UploadEvent
from app.models.log import InteractionLog, RiskLog, OperationLog, SystemConfig
from app.models.notification import Notification, NotificationPreference
from app.models.privacy import PrivacySetting
from app.models.agent_memory import AgentMemory, AgentFeedback

__all__ = [
    "User", "EmailVerificationCode",
    "Course", "CourseMaterial", "KnowledgePoint", "MaterialParseJob",
    "StudentProfile", "MasteryRecord", "WrongQuestion", "ReviewPlan",
    "PracticeRecord", "InterviewRecord",
    "Classroom", "ClassMember", "CourseEnrollment", "CourseCollaborator", "CourseShare",
    "Conversation", "ChatMessage", "KnowledgeDraft", "InterviewAssignment",
    "Assignment", "Submission",
    "Question", "QuestionDraft", "Exam", "ExamPlanDraft", "ExamQuestion",
    "ExamRecord", "ExamSession",
    "UploadEvent",
    "InteractionLog", "RiskLog", "OperationLog", "SystemConfig",
    "Notification", "NotificationPreference",
    "PrivacySetting",
    "AgentMemory", "AgentFeedback",
]
