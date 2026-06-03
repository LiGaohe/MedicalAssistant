"""验证数据库结构"""
from sqlalchemy import create_engine, text

engine = create_engine('sqlite:///data/database/benchmark.db')

with engine.connect() as conn:
    result = conn.execute(text('PRAGMA table_info(benchmark_runs)'))
    print('benchmark_runs 表结构:')
    for row in result.fetchall():
        print(f'  {row[1]}: {row[2]}')
    
    result = conn.execute(text('SELECT COUNT(*) FROM benchmark_runs'))
    count = result.fetchone()[0]
    print(f'\n现有数据: {count} 条记录')