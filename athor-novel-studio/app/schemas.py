from pydantic import BaseModel


class OutlineRequest(BaseModel):
    userinput: str
    session_id: str | None = None


class ReviewRequest(BaseModel):
    outline_id: int | None = None
    decision: str
    comment: str = ""
    session_id: str | None = None


class OutlineUpdate(BaseModel):
    content: str
    comment: str = ""
    session_id: str | None = None


class OutlineReviseRequest(BaseModel):
    outline_id: int
    comment: str
    session_id: str | None = None


class ChapterRequest(BaseModel):
    chapter_outline_id: int | None = None
    novel_chapter_id: int | None = None
    outline_id: int | None = None
    rewrite: bool = False
    resume: bool = False
    audit_issues: str = ""
    content_issues: str = ""
    ai_issues: str = ""
    scene_choice: str = ""
    session_id: str | None = None


class ShortOptionsRequest(BaseModel):
    short_id: int
    force: bool = False
    note: str = ""
    session_id: str | None = None


class ShortChoiceRequest(BaseModel):
    short_id: int
    choice_no: int | None = None
    note: str = ""
    session_id: str | None = None


class ChapterIdRequest(BaseModel):
    novel_chapter_id: int
    session_id: str | None = None


class SessionCreate(BaseModel):
    userinput: str = ""
    title: str | None = None


class SessionUpdate(BaseModel):
    title: str


class StructureRequest(BaseModel):
    outline_id: int | None = None
    session_id: str | None = None


class VolumeRequest(BaseModel):
    outline_id: int | None = None
    session_id: str | None = None
    volume_no: int | None = None
