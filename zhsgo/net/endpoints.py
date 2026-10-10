"""接口地址常量。

原项目把 URL 散落在 60 多个方法里，改域名要全文件搜索。这里集中管理，
并保留原始注释里的"官方拼写错误"标注 —— `queryStuyInfo` 这种坑下次不会踩。
"""
from __future__ import annotations

# ------------------------------------------------------------------ 登录
PASSPORT = "https://passport.zhihuishu.com"
LOGIN_PAGE = f"{PASSPORT}/login?service=https://onlineservice-api.zhihuishu.com/login/gologin"
VALIDATE_ACCOUNT = f"{PASSPORT}/user/validateAccountAndPassword"
CHECK_NEED_AUTH = "https://appcomm-user.zhihuishu.com/app-commserv-user/userInfo/checkNeedAuth"
QR_IMAGE = f"{PASSPORT}/qrCodeLogin/getLoginQrImg"
QR_INFO = f"{PASSPORT}/qrCodeLogin/getLoginQrInfo"

# ---------------------------------------------------------------- 共享课
STUDY_API = "https://studyservice-api.zhihuishu.com"
ZHIDAO_GOLOGIN = f"{STUDY_API}/login/gologin"
ZHIDAO_QUERY_COURSE = f"{STUDY_API}/gateway/t/v1/learning/queryCourse"
ZHIDAO_VIDEO_LIST = f"{STUDY_API}/gateway/t/v1/learning/videolist"
ZHIDAO_STUDY_READ_BEFORE = f"{STUDY_API}/gateway/t/v1/learning/queryStudyReadBefore"
ZHIDAO_STUDY_INFO = f"{STUDY_API}/gateway/t/v1/learning/queryStuyInfo"  # 官方拼写错误，勿改
ZHIDAO_LAST_VIDEO = f"{STUDY_API}/gateway/t/v1/learning/queryUserRecruitIdLastVideoId"
ZHIDAO_PRELEARNING_NOTE = f"{STUDY_API}/gateway/t/v1/learning/prelearningNote"
ZHIDAO_POINTER_INFO = f"{STUDY_API}/gateway/t/v1/popupAnswer/loadVideoPointerInfo"
ZHIDAO_POPUP_EXAM = f"{STUDY_API}/gateway/t/v1/popupAnswer/lessonPopupExam"
ZHIDAO_POPUP_SAVE_ANSWER = f"{STUDY_API}/gateway/t/v1/popupAnswer/saveLessonPopupExamSaveAnswer"
ZHIDAO_SAVE_DB_V2 = f"{STUDY_API}/gateway/t/v1/learning/saveDatabaseIntervalTimeV2"
ZHIDAO_SAVE_DB_V1 = f"{STUDY_API}/gateway/t/v1/learning/saveDatabaseIntervalTime"
ZHIDAO_SAVE_CACHE = f"{STUDY_API}/gateway/t/v1/learning/saveCacheIntervalTime"
ZHIDAO_THREE_DIM = f"{STUDY_API}/gateway/t/v1/course/threeDimensionalCourseWare"

ONLINE_API = "https://onlineservice-api.zhihuishu.com"
ZHIDAO_SHARE_LIST = f"{ONLINE_API}/gateway/t/v1/student/course/share/queryShareCourseInfo"
AI_COURSE_LIST = f"{ONLINE_API}/gateway/t/v1/student/queryStudentAICourseList"

# ---------------------------------------------------------------- 校内课
HIKE_COURSE_LIST = "https://hikeservice.zhihuishu.com/student/course/aided/getMyCourseList"
HIKE_MENU_TREE = "https://studyresources.zhihuishu.com/studyResources/stuResouce/queryResourceMenuTree"
HIKE_VIEW_FILE = "https://studyresources.zhihuishu.com/studyResources/stuResouce/stuViewFile"
HIKE_SAVE_RECORD = "https://hike-teaching.zhihuishu.com/stuStudy/saveStuStudyRecord"

# ------------------------------------------------------------------ 视频
VIDEO_INIT = "https://newbase.zhihuishu.com/video/initVideo"

# ---------------------------------------------------------------- AI 课程
AI_API = "https://kg-ai-run.zhihuishu.com/run/gateway/t/stu"
AI_COURSE_BASIC = f"{AI_API}/knowledge-study/course-basic"
AI_RESOURCE_LIST = f"{AI_API}/resources/list-knowledge-resource"
AI_RESOURCE_COMPLETE = f"{AI_API}/studyRecord/completed"
AI_REPORT = f"{AI_API}/studyRecord/report"
AI_VIDEO_TIME = f"{AI_API}/resources-lab/get-video-time"
AI_EXAM_PAPER = f"{AI_API}/exam/questions-paper"

# ---------------------------------------------------------------- AI 考试
EXAM_API = "https://studentexamtest.zhihuishu.com/gateway/t/v1"
EXAM_OPEN = f"{EXAM_API}/exam/user/openExam"
EXAM_HEARTBEAT = f"{EXAM_API}/exam/user/updateUserUsedTime"
EXAM_SHEET = f"{EXAM_API}/exam/user/getExamSheetInfo"
EXAM_QUESTION = f"{EXAM_API}/question/getExamQuestionInfo"
EXAM_SAVE_ANSWER = f"{EXAM_API}/answer/saveAnswer"
EXAM_SUBMIT = f"{EXAM_API}/exam/user/submit"

# ------------------------------------------------------- 智慧树自带大模型
ZHS_LLM_STREAM = (
    "https://ai-knowledge-map-platform.zhihuishu.com"
    "/knowledgemap/gateway/t/qa/platform/stream"
)

# ------------------------------------------------------------ 业务错误码
CODE_OK_ZHIDAO = 0
CODE_OK_HOME = 200
CODE_OK_HIKE = 200
CODE_CAPTCHA = -12          # 服务端风控：要求人机验证
CODE_LOGIN_BAD_PASSWORD = -2
CODE_LOGIN_TOO_MANY = -4
CODE_LOGIN_NEED_SMS = -9
