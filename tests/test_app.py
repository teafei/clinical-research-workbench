"""Streamlit workflow tests; no real records or models are accessed."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / 'app.py'
PAGES = ['工作台总览', '导入与标准化', '数据质控', '队列与统计', '病历结构化', '导出与审计']


def button(app, label):
    return next(b for b in app.button if b.label == label)


class AppWorkflowTests(unittest.TestCase):
    def create(self):
        app = AppTest.from_file(str(APP), default_timeout=20).run()
        self.assertEqual(len(app.exception), 0)
        return app

    def test_all_six_pages_render_and_export_manifest_is_auditable(self):
        app = self.create()
        self.assertEqual([m.value for m in app.metric], ['80', '101', '80', '80'])
        for page in PAGES:
            app.radio(key='navigation').set_value(page).run()
            self.assertEqual(len(app.exception), 0, page)
        self.assertEqual(len(app.get('download_button')), 2)
        self.assertIn('one_encounter_per_selected_patient', app.json[0].value)

    def test_cohort_filters_persist_and_reset(self):
        app = self.create()
        app.radio(key='navigation').set_value('队列与统计').run()
        app.multiselect(key='filter_procedure').set_value(['PKP'])
        app.checkbox(key='filter_first').uncheck()
        button(app, '更新队列').click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state['spec'].procedures, ('PKP',))
        self.assertFalse(app.session_state['spec'].first_per_patient)
        self.assertGreater(int(app.metric[2].value), 0)
        button(app, '重置为合成演示').click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state['spec'].procedures, ())

    def test_review_requires_reviewer_and_source_change_clears_candidates(self):
        app = self.create()
        app.radio(key='navigation').set_value('病历结构化').run()
        button(app, '生成待审核候选').click().run()
        self.assertEqual(len(app.session_state['extract_candidates']), 5)
        app.button(key='review_yes_0').click().run()
        self.assertEqual(len(app.session_state['review_log']), 0)
        self.assertTrue(any('审核者' in e.value for e in app.error))
        app.text_input(key='review_name').set_value('synthetic-reviewer')
        app.button(key='review_yes_0').click().run()
        self.assertEqual(app.session_state['review_log'][-1]['review_status'], 'accepted')
        app.button(key='review_no_0').click().run()
        self.assertEqual(app.session_state['review_log'][-1]['review_status'], 'rejected')
        app.selectbox(key='extract_note').set_value('B 已实施与培养阴性').run()
        self.assertEqual(app.session_state['extract_candidates'], [])
        self.assertEqual(app.session_state['review_log'], [])
        self.assertEqual(len(app.exception), 0)

    def test_import_format_switch_and_missing_files_message(self):
        app = self.create()
        app.radio(key='navigation').set_value('导入与标准化').run()
        next(r for r in app.radio if r.label == '文件格式').set_value('三个 CSV 文件').run()
        self.assertEqual(len(app.get('file_uploader')), 3)
        button(app, '验证并导入').click().run()
        self.assertTrue(any('全部三个' in e.value for e in app.error))
        self.assertEqual(len(app.exception), 0)

    def test_public_demo_disables_upload_and_local_text_connection(self):
        with patch.dict(os.environ, {'CRW_PUBLIC_DEMO': '1'}):
            app = self.create()
            app.radio(key='navigation').set_value('导入与标准化').run()
            self.assertEqual(len(app.get('file_uploader')), 0)
            app.radio(key='navigation').set_value('病历结构化').run()
            app.radio(key='extract_mode').set_value('本地 Ollama 模型').run()
            self.assertTrue(app.text_area(key='extract_local_source').disabled)
            self.assertTrue(button(app, '生成待审核候选').disabled)
            self.assertEqual(len(app.exception), 0)


if __name__ == '__main__':
    unittest.main()
