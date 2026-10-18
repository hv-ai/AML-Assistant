import os
bind='0.0.0.0:'+os.environ.get('PORT','8080')
# Keep one process/instance: runtime caches, usage guards and the pilot budget
# share the same filesystem. Multi-instance hosting needs a shared data store.
workers=1
worker_class='gthread'
threads=12
timeout=180
accesslog=None
errorlog='-'
