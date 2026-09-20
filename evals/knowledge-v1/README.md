# knowledge-v1-dev-seen

8个作者已见SYNTHETIC单主题问题：7个有支持文档，1个无依据。每篇文档在本版只有一个片段，所以supporting_doc_ids既是检索目标，也是当前回答支持标注；以后切成多段必须新增片段级gold，不能继续把整篇命中当成支持。

`uv run python evals/evaluate_knowledge.py --output .runtime/knowledge-new.json`使用真实本地中文编码和pgvector，不发DeepSeek请求。先安装项目PG/pgvector、加载Env，并按uv.lock安装fastembed。首次下载公共模型到.runtime，随后按manifest本地加载并校验文件摘要。

同一语料/问题比较vector与hybrid，分别报告recall@3/MRR、回答支持比例、原文保真度及无依据判断。未知分母用null，不写成0或成功。结果独占创建，失败与部分已完成步骤保留；当前没有语义holdout或LLM答案质量结论。WP03的v1/v2保留了回答选择改动及混合检索无收益的结果。
