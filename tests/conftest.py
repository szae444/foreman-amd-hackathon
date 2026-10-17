import os
import tempfile

# Must run before foreman.config is imported anywhere.
os.environ["FOREMAN_LLM_MODE"] = "mock"
os.environ["FOREMAN_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="foreman-test-"), "test.db")
