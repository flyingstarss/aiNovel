SET FOREIGN_KEY_CHECKS=0;

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `chapter_outline` (
  `id` int NOT NULL AUTO_INCREMENT,
  `short_id` int NOT NULL COMMENT '所属短纲',
  `chapter_no` int NOT NULL COMMENT '短纲内章节序号',
  `title` varchar(128) DEFAULT NULL COMMENT '章节名',
  `summary` text COMMENT '章节梗概',
  `purpose` text COMMENT '本章写作目的',
  `scene` text COMMENT '场景',
  `characters` text COMMENT '出场人物',
  `conflict` text COMMENT '本章冲突',
  `ending_hook` text COMMENT '章尾钩子',
  `target_words` int DEFAULT NULL COMMENT '建议字数',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_chapter` (`short_id`,`chapter_no`),
  CONSTRAINT `fk_chapter_short` FOREIGN KEY (`short_id`) REFERENCES `short_outline` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=159 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `foreshadow` (
  `id` int NOT NULL AUTO_INCREMENT,
  `outline_id` int DEFAULT NULL COMMENT '所属全书大纲',
  `name` varchar(128) NOT NULL COMMENT '伏笔名称',
  `content` text COMMENT '伏笔内容',
  `plant_place` varchar(255) DEFAULT NULL COMMENT '埋设位置（卷/章）',
  `clue` text COMMENT '线索细节',
  `reveal_place` varchar(255) DEFAULT NULL COMMENT '揭晓位置（卷/章）',
  `payoff` text COMMENT '回收方式与效果',
  `related_characters` text COMMENT '关联人物',
  `importance` varchar(32) DEFAULT NULL COMMENT '重要程度：核心/主线/支线',
  `status` varchar(32) DEFAULT '未回收' COMMENT '状态',
  `last_chapter_no` int DEFAULT NULL COMMENT '最后推进章节号',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_foreshadow_outline_name` (`outline_id`,`name`)
) ENGINE=InnoDB AUTO_INCREMENT=21 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `novel_chapter` (
  `id` int NOT NULL AUTO_INCREMENT,
  `chapter_outline_id` int NOT NULL COMMENT '对应章纲',
  `chapter_no` int NOT NULL COMMENT '短纲内章节序号',
  `title` varchar(128) DEFAULT NULL COMMENT '章节标题',
  `content` longtext COMMENT '正文',
  `word_count` int DEFAULT NULL COMMENT '正文字数',
  `summary` text COMMENT '本章摘要',
  `summary_points` text COMMENT '关键情节点',
  `summary_characters` text COMMENT '本章出场人物',
  `summary_foreshadow` text COMMENT '涉及伏笔及推进情况',
  `summary_time` datetime DEFAULT NULL COMMENT '摘要生成时间',
  `status` varchar(32) NOT NULL DEFAULT '已完成' COMMENT '状态：草稿/已完成',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '正文生成时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_chapter_outline` (`chapter_outline_id`),
  CONSTRAINT `fk_novel_chapter_outline` FOREIGN KEY (`chapter_outline_id`) REFERENCES `chapter_outline` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `novel_session` (
  `session_id` varchar(64) NOT NULL COMMENT '会话 id（即 LangGraph thread_id）',
  `title` varchar(128) DEFAULT NULL COMMENT '会话标题',
  `userinput` text COMMENT '用户需求',
  `status` varchar(32) DEFAULT '进行中' COMMENT '状态：进行中/大纲待审核/大纲已通过/大纲已驳回/写作中/已完成',
  `outline_id` int DEFAULT NULL COMMENT '当前大纲 id',
  `current_chapter_id` int DEFAULT NULL COMMENT '当前章纲 id',
  `current_novel_chapter_id` int DEFAULT NULL COMMENT '当前正文 id',
  `message` text COMMENT '最近一次提示信息',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`session_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `outline` (
  `id` int NOT NULL AUTO_INCREMENT,
  `title` varchar(128) NOT NULL COMMENT '书名',
  `theme` text COMMENT '主题',
  `logline` text COMMENT '一句话故事',
  `core_conflict` text COMMENT '核心矛盾',
  `setting` text COMMENT '故事背景与舞台',
  `protagonist_arc` text COMMENT '主角成长弧线',
  `antagonist_arc` text COMMENT '反派/阻力方弧线',
  `main_plot` text COMMENT '主线剧情走向',
  `sub_plots` text COMMENT '支线剧情',
  `act_qi` text COMMENT '起',
  `act_cheng` text COMMENT '承',
  `act_zhuan` text COMMENT '转',
  `act_he` text COMMENT '合',
  `ending` text COMMENT '结局',
  `keywords` text COMMENT '关键词',
  `content` longtext COMMENT '大纲 Markdown 原文',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `status` varchar(16) DEFAULT '待审核' COMMENT '审核状态：待审核/已通过/已驳回',
  `review_comment` text COMMENT '审核意见',
  `review_time` datetime DEFAULT NULL COMMENT '审核时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_outline_title` (`title`)
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `outline_revision` (
  `id` int NOT NULL AUTO_INCREMENT,
  `outline_id` int NOT NULL COMMENT '所属大纲',
  `title` varchar(128) DEFAULT NULL COMMENT '书名快照',
  `content` longtext COMMENT '该版本的大纲原文',
  `status` varchar(16) DEFAULT NULL COMMENT '该版本状态',
  `comment` text COMMENT '修改说明',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_outline` (`outline_id`),
  CONSTRAINT `fk_revision_outline` FOREIGN KEY (`outline_id`)
    REFERENCES `outline` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `person` (
  `id` char(64) NOT NULL COMMENT 'sha256(name)',
  `name` varchar(64) NOT NULL COMMENT '姓名',
  `age` int DEFAULT NULL COMMENT '年龄',
  `gender` varchar(16) DEFAULT NULL COMMENT '性别',
  `appear` text COMMENT '外貌',
  `charTr` text COMMENT '性格',
  `situat` text COMMENT '处境',
  `ability` text COMMENT '能力',
  `goal` text COMMENT '核心目标',
  `relation` text COMMENT '与其他人物关系',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `first_volume_no` int DEFAULT NULL COMMENT '首次登场卷序号，NULL 表示全书通用',
  `outline_id` int DEFAULT NULL COMMENT '所属全书大纲，用于按书隔离',
  `current_state` text COMMENT '截至最新章节的状态',
  `current_location` varchar(255) DEFAULT NULL COMMENT '当前所在地点',
  `last_chapter_no` int DEFAULT NULL COMMENT '状态更新到的章节号',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_person_outline_name` (`outline_id`,`name`),
  KEY `idx_first_volume` (`first_volume_no`),
  KEY `idx_person_outline` (`outline_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `person_relation` (
  `id` char(64) NOT NULL COMMENT 'sha256(name_a||name_b)',
  `person_id_a` char(64) NOT NULL COMMENT 'sha256(name_a)',
  `person_id_b` char(64) NOT NULL COMMENT 'sha256(name_b)',
  `relation_desc` text NOT NULL COMMENT '关系描述',
  `relation_type` varchar(20) DEFAULT NULL COMMENT '关系类型：正向/敌对/中立',
  `name_a` varchar(64) NOT NULL COMMENT '人物A名称',
  `name_b` varchar(64) NOT NULL COMMENT '人物B名称',
  `outline_id` int DEFAULT NULL COMMENT '所属全书大纲，用于按书隔离',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_person_a` (`person_id_a`),
  KEY `idx_person_b` (`person_id_b`),
  KEY `idx_relation_outline` (`outline_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `review_record` (
  `id` int NOT NULL AUTO_INCREMENT,
  `target_type` varchar(32) NOT NULL COMMENT '审核对象类型：outline/chapter',
  `target_id` int NOT NULL COMMENT '审核对象 id',
  `review_type` varchar(32) NOT NULL COMMENT '审核类型：human_outline/violation/consistency',
  `passed` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否通过',
  `risk_level` varchar(16) DEFAULT NULL COMMENT '风险等级',
  `issues` text COMMENT '问题说明',
  `suggestion` text COMMENT '修改建议',
  `reviewer` varchar(64) DEFAULT 'system' COMMENT '审核方：user/system',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_target` (`target_type`,`target_id`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `short_outline` (
  `id` int NOT NULL AUTO_INCREMENT,
  `volume_id` int NOT NULL COMMENT '所属分卷',
  `seq` int NOT NULL COMMENT '卷内序号，从 1 开始',
  `title` varchar(128) DEFAULT NULL COMMENT '短纲标题',
  `storyline` text COMMENT '故事详细走向',
  `goal` text COMMENT '这段故事的目标',
  `conflict` text COMMENT '核心冲突',
  `turning_point` text COMMENT '转折点',
  `key_events` text COMMENT '关键事件',
  `characters` text COMMENT '涉及人物',
  `location` varchar(255) DEFAULT NULL COMMENT '发生地点',
  `chapter_span` varchar(64) DEFAULT NULL COMMENT '预计覆盖章节范围',
  `result` text COMMENT '段落结果',
  `start_state` text COMMENT '本段开头状态',
  `end_state` text COMMENT '本段最终结果（第 3 章必须落到这里）',
  `chapter_count` tinyint NOT NULL DEFAULT 3 COMMENT '本段覆盖章数',
  `segment_mode` tinyint NOT NULL DEFAULT 0 COMMENT '0=旧机制 1=三章一节点',
  `plot_options` longtext COMMENT '3 个候选走向（JSON）',
  `plot_choice_no` tinyint DEFAULT NULL COMMENT '选中的走向序号 1-3',
  `plot_choice_mode` varchar(16) DEFAULT NULL COMMENT 'manual=人工选定 auto=模型自行处理',
  `plot_choice` longtext COMMENT '选中走向的文本快照',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_short` (`volume_id`,`seq`),
  CONSTRAINT `fk_short_volume` FOREIGN KEY (`volume_id`) REFERENCES `volume` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=56 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `story_map` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL COMMENT '地点名',
  `type` varchar(32) DEFAULT NULL COMMENT '类型：大陆/国家/城市/山脉/秘境等',
  `parent_name` varchar(128) DEFAULT NULL COMMENT '上级地点',
  `region` varchar(128) DEFAULT NULL COMMENT '所属区域',
  `description` text COMMENT '地点描述',
  `terrain` text COMMENT '地貌',
  `climate` text COMMENT '气候',
  `resources` text COMMENT '资源物产',
  `inhabitants` text COMMENT '居住人群/势力',
  `story_function` text COMMENT '在故事中的作用',
  `related_events` text COMMENT '关联事件',
  `outline_id` int DEFAULT NULL COMMENT '所属全书大纲，用于按书隔离',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_map_outline_name` (`outline_id`,`name`)
) ENGINE=InnoDB AUTO_INCREMENT=25 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `violation_word` (
  `id` int NOT NULL AUTO_INCREMENT,
  `word` varchar(64) NOT NULL COMMENT '违规词',
  `category` varchar(32) DEFAULT NULL COMMENT '分类：色情低俗/暴力血腥/违法犯罪/违禁物品/恐怖暴力/歧视侮辱',
  `level` varchar(16) DEFAULT NULL COMMENT '等级：高/中/低',
  `action` varchar(16) DEFAULT NULL COMMENT '处置：拦截/警告/人工复核',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_word` (`word`)
) ENGINE=InnoDB AUTO_INCREMENT=39 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `volume` (
  `id` int NOT NULL AUTO_INCREMENT,
  `outline_id` int NOT NULL COMMENT '所属全书大纲',
  `volume_no` int NOT NULL COMMENT '卷序号，从 1 开始',
  `title` varchar(128) NOT NULL COMMENT '卷名',
  `summary` text COMMENT '本卷梗概',
  `volume_function` text COMMENT '本卷在全书结构中的作用',
  `conflict` text COMMENT '本卷主要矛盾',
  `start_state` text COMMENT '开卷状态',
  `end_state` text COMMENT '收卷状态',
  `qi` text COMMENT '本卷之起',
  `cheng` text COMMENT '本卷之承',
  `zhuan` text COMMENT '本卷之转',
  `he` text COMMENT '本卷之合',
  `main_characters` text COMMENT '主要出场人物',
  `key_events` text COMMENT '关键事件',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_volume` (`outline_id`,`volume_no`),
  CONSTRAINT `fk_volume_outline` FOREIGN KEY (`outline_id`) REFERENCES `outline` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=22 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `worldview` (
  `id` int NOT NULL AUTO_INCREMENT,
  `spacetime` text COMMENT '所处时空',
  `rule` text COMMENT '世界规则',
  `geoEco` text COMMENT '地理生态',
  `history` text COMMENT '既往历史',
  `populace` text COMMENT '人群分类',
  `socPower` text COMMENT '社会的权力架构',
  `econLife` text COMMENT '经济日常',
  `culture` text COMMENT '文化和信仰',
  `powerSys` text COMMENT '小说里的能力体系',
  `outline_id` int DEFAULT NULL COMMENT '所属全书大纲，用于按书隔离',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

LOCK TABLES `violation_word` WRITE;
/*!40000 ALTER TABLE `violation_word` DISABLE KEYS */;
INSERT IGNORE INTO `violation_word` (`id`, `word`, `category`, `level`, `action`, `create_time`) VALUES (1,'色情','色情低俗','高','拦截','2026-11-19 18:03:10'),(2,'裸露','色情低俗','中','警告','2026-11-19 18:03:10'),(3,'嫖娼','色情低俗','高','拦截','2026-11-19 18:03:10'),(4,'强奸','色情低俗','高','拦截','2026-11-19 18:03:10'),(5,'毒品','违法犯罪','高','拦截','2026-11-19 18:03:10'),(6,'吸毒','违法犯罪','高','拦截','2026-11-19 18:03:10'),(7,'贩毒','违法犯罪','高','拦截','2026-11-19 18:03:10'),(8,'制毒','违法犯罪','高','拦截','2026-11-19 18:03:10'),(9,'赌博','违法犯罪','高','拦截','2026-11-19 18:03:10'),(10,'枪支','违禁物品','高','拦截','2026-11-19 18:03:10'),(11,'弹药','违禁物品','高','拦截','2026-11-19 18:03:10'),(12,'炸药','违禁物品','高','拦截','2026-11-19 18:03:10'),(13,'恐怖袭击','恐怖暴力','高','拦截','2026-11-19 18:03:10'),(14,'肢解','暴力血腥','高','拦截','2026-11-19 18:03:10'),(15,'虐待','暴力血腥','中','人工复核','2026-11-19 18:03:10'),(16,'自杀','暴力血腥','高','人工复核','2026-11-19 18:03:10'),(17,'自残','暴力血腥','中','人工复核','2026-11-19 18:03:10'),(18,'歧视','歧视侮辱','中','警告','2026-11-19 18:03:10'),(19,'辱骂','歧视侮辱','低','警告','2026-11-19 18:03:10');
INSERT IGNORE INTO `violation_word` (`word`, `category`, `level`, `action`) VALUES ('儿童色情','色情低俗','高','拦截'),('迷奸','色情低俗','高','拦截'),('卖淫','色情低俗','高','拦截'),('猥亵','色情低俗','高','拦截'),('性侵','色情低俗','高','拦截'),('冰毒','违法犯罪','高','拦截'),('海洛因','违法犯罪','高','拦截'),('大麻','违法犯罪','高','拦截'),('摇头丸','违法犯罪','高','拦截'),('制枪','违禁物品','高','拦截'),('爆炸物','违禁物品','高','拦截'),('炸弹制作','违禁物品','高','拦截'),('恐怖组织','恐怖暴力','高','拦截'),('邪教','违法犯罪','中','人工复核'),('分裂国家','政治敏感','高','拦截'),('颠覆国家','政治敏感','高','拦截'),('侮辱英烈','政治敏感','高','拦截'),('民族仇恨','歧视侮辱','高','拦截'),('种族歧视','歧视侮辱','中','警告'),('拐卖妇女','违法犯罪','高','拦截'),('拐卖儿童','违法犯罪','高','拦截'),('虐待儿童','暴力血腥','高','拦截'),('血腥肢解','暴力血腥','高','拦截'),('详细自杀方法','暴力血腥','高','拦截'),('教唆自残','暴力血腥','高','拦截');
/*!40000 ALTER TABLE `violation_word` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

SET FOREIGN_KEY_CHECKS=1;
