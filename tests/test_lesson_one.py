import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.profiles.coze import CozeAssessor, CozeVariableWriter, UpstreamError
from backend.profiles.scoring import (OPTIONS, Questionnaire, ValidationError,
                                      normalize_choice, score, score_semantic)
from backend.profiles.service import ProfileApplication
from tools.import_questionnaires import FIELDS, read_xlsx, write_template


def survey(text='看过很多图片总结规律，再画出新的图', **answers):
    return {'class_no': 8, 'student_no': 55,
            'answers': {'q5': 'C', 'q7': 'C', 'q8': 'C', 'q9': 'B', 'q10': 'C',
                        'q11': text, **answers}}


def assessment(text='总结规律', category='pattern_generation', confidence=0.95):
    return {'category': category, 'confidence': confidence,
            'evidence': [text], 'reason': '引用原文说明判断依据'}


class MemoryStore:
    def __init__(self):
        self.data = {}

    def get(self, kind, key):
        return copy.deepcopy(self.data.get((kind, key)))

    def put(self, kind, key, value):
        self.data[kind, key] = copy.deepcopy(value)

    def create(self, kind, key, value):
        if (kind, key) in self.data:
            return False
        self.put(kind, key, value)
        return True


class FakeAssessor:
    calls = 0
    result = None

    def assess(self, questionnaire):
        self.calls += 1
        return self.result or assessment()


class FakeAuth:
    calls = 0
    changed = False

    def issue(self, user_id):
        self.calls += 1
        return {'token': f'fresh-token-{self.calls}',
                'user_id_hash': 'changed' if self.changed else 'stable-hashed-id'}


class ScoringTests(unittest.TestCase):
    def test_full_score_and_special_question_nine(self):
        q = Questionnaire.parse(survey())
        result = score(q, assessment())
        self.assertEqual((result['total'], result['preconception']), (100, 'P3'))
        for letter, points in [('A', 4), ('B', 6), ('C', 2), ('D', 0)]:
            self.assertEqual(score(Questionnaire.parse(survey(q9=letter)), assessment())['objective_points']['q9'], points)

    def test_reordered_content_wins_over_letter(self):
        self.assertEqual(normalize_choice(9, 'C. ' + OPTIONS[9][1]), 'B')
        with self.assertRaises(ValidationError):
            normalize_choice(5, '未知选项')

    def test_p0_and_unscored_empty_answer(self):
        result = score(Questionnaire.parse(survey('', q5='D', q7='D', q8='D', q9='D', q10='D')), None)
        self.assertIsNone(result['open_points'])
        self.assertEqual((result['total'], result['preconception']), (0, 'P0'))

    def test_level_threshold_neighbours(self):
        # All possible objective scores are even; test each reachable boundary neighbour.
        cases = [(18, None, 'P0'), (20, None, 'P1'), (44, 'retrieval', 'P1'),
                 (46, 'retrieval', 'P2'), (74, 'pattern_generation', 'P2'),
                 (76, 'pattern_generation', 'P3')]
        import itertools
        for total, category, expected in cases:
            open_score = {None: 0, 'retrieval': 40, 'pattern_generation': 70}[category]
            for letters in itertools.product('ABCD', repeat=5):
                payload = survey('总结规律' if category else '', **dict(zip(('q5', 'q7', 'q8', 'q9', 'q10'), letters)))
                result = score(Questionnaire.parse(payload), assessment(category=category) if category else None)
                if result['total'] == total:
                    self.assertEqual(result['preconception'], expected)
                    break
            else:
                self.fail(f'No reachable fixture for {total - open_score}')

    def test_low_confidence_never_assigns_a_level(self):
        result = score(Questionnaire.parse(survey()), assessment(confidence=0.5))
        self.assertEqual(result['status'], 'needs_review')
        self.assertIsNone(result['total'])
        self.assertIsNone(result['preconception'])

    def test_evidence_and_schema_validation(self):
        for result in [assessment('编造证据'), assessment(confidence=float('nan')),
                       assessment(category=[]), assessment() | {'total': 100},
                       assessment(category='mixed')]:
            with self.subTest(result=result), self.assertRaises(ValidationError):
                score(Questionnaire.parse(survey()), result)
        mixed = assessment(category='mixed') | {'evidence': ['总结规律', '很多图片']}
        self.assertEqual(score(Questionnaire.parse(survey()), mixed)['open_points'], 30)

    def test_identity_and_digest(self):
        self.assertEqual(Questionnaire.parse(survey()).digest,
                         Questionnaire.parse(survey() | {'class_no': '8.0'}).digest)
        for invalid in [True, 0, 9, '8班', '1;drop']:
            with self.assertRaises(ValidationError):
                Questionnaire.parse(survey() | {'class_no': invalid})


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.store, self.assessor, self.auth = MemoryStore(), FakeAssessor(), FakeAuth()
        self.now = 1000
        self.app = ProfileApplication(self.store, self.assessor, self.auth,
                                      'i' * 32, 'a' * 32, 'p' * 32, clock=lambda: self.now)

    def call(self, path, body, key=None, origin=None):
        headers = {'x-admin-key': 'a' * 32} if key == 'admin' else {'x-coze-plugin-key': 'p' * 32} if key == 'plugin' else {}
        if origin: headers['Origin'] = origin
        result = self.app.handle({'httpMethod': 'POST', 'path': path,
                                 'headers': headers, 'body': json.dumps(body)})
        return result['statusCode'], json.loads(result['body'])

    def seed(self):
        status, body = self.call('/admin/questionnaires', survey(), 'admin')
        self.assertEqual(status, 200, body)
        return body['data']

    def test_student_login_plugin_and_fresh_token_loop(self):
        self.seed()
        status, response = self.call('/auth', {'user_id': '8班_55_1'})
        self.assertEqual(status, 200)
        public = response['data']
        self.assertEqual(set(public), {'token', 'user_id_hash', 'profile_ref', 'bot_id'})
        self.assertEqual(public['bot_id'], '7706348792413011968')
        status, profile = self.call('/internal/profile', {'profile_ref': public['profile_ref']}, 'plugin')
        self.assertEqual(status, 200)
        self.assertEqual(profile['data']['preconception'], 'P3')
        self.assertNotIn('answers', profile['data'])
        status, renewed = self.call('/auth', {'user_id': '8班_55_1', 'profile_ref': public['profile_ref']})
        self.assertEqual(status, 200)
        self.assertNotEqual(renewed['data']['token'], public['token'])
        self.assertEqual(renewed['data']['profile_ref'], public['profile_ref'])

    def test_protected_routes_cannot_be_read_or_written_by_student(self):
        for path in ['/admin/questionnaires', '/admin/review', '/admin/profile', '/internal/profile']:
            self.assertEqual(self.call(path, {})[0], 401)
        self.assertFalse(self.store.data)

    def test_repeated_import_is_idempotent_and_changes_require_digest(self):
        old = self.seed()
        self.assertTrue(self.call('/admin/questionnaires', survey(), 'admin')[1]['data']['unchanged'])
        self.assertEqual(self.assessor.calls, 1)
        new = survey(q5='A')
        self.assertEqual(self.call('/admin/questionnaires', new, 'admin')[0], 409)
        self.assertEqual(self.call('/admin/questionnaires', new | {'replace_digest': old['source_digest']}, 'admin')[0], 200)

    def test_bad_model_output_is_stored_for_teacher_review(self):
        self.assessor.result = assessment('伪造原文')
        old = self.seed()
        self.assertEqual(old['status'], 'needs_review')
        self.assertEqual(self.call('/auth', {'user_id': '8班_55_1'})[0], 409)
        status, raw = self.call('/admin/profile', {'class_no': 8, 'student_no': 55}, 'admin')
        self.assertEqual(status, 200)
        self.assertEqual(raw['data']['answers']['q11'], survey()['answers']['q11'])
        review = {'class_no': 8, 'student_no': 55, 'source_digest': old['source_digest'],
                  'assessment': assessment(confidence=1)}
        self.assertEqual(self.call('/admin/review', review | {'source_digest': 'stale'}, 'admin')[0], 409)
        self.assertEqual(self.call('/admin/review', review, 'admin')[1]['data']['preconception'], 'P3')
        self.assertEqual(self.call('/auth', {'user_id': '8班_55_1'})[0], 200)

    def test_missing_profile_does_not_get_a_default_level(self):
        self.assertEqual(self.call('/auth', {'user_id': '8班_55_1'})[0], 409)
        self.assertEqual(self.auth.calls, 0)

    def test_ticket_expiry_and_identity_binding(self):
        self.seed()
        ticket = self.call('/auth', {'user_id': '8班_55_1'})[1]['data']['profile_ref']
        self.call('/admin/questionnaires', survey() | {'student_no': 1}, 'admin')
        self.assertEqual(self.call('/auth', {'user_id': '8班_1_1', 'profile_ref': ticket})[0], 403)
        self.auth.changed = True
        self.assertEqual(self.call('/auth', {'user_id': '8班_55_1', 'profile_ref': ticket})[0], 403)
        self.now += 4 * 3600
        self.assertEqual(self.call('/internal/profile', {'profile_ref': ticket}, 'plugin')[0], 401)

    def test_only_lesson_one_valid_class_and_allowed_origin(self):
        for user in ['8班_55_2', '9班_1_1', '1班_56_1', '1班_0_1']:
            self.assertEqual(self.call('/auth', {'user_id': user})[0], 422)
        self.assertEqual(self.call('/auth', {}, origin='https://evil.example')[0], 403)

    def test_failure_messages_do_not_expose_answers_or_tokens(self):
        with patch.object(self.assessor, 'assess', side_effect=RuntimeError('secret-token and student text')):
            status, body = self.call('/admin/questionnaires', survey(), 'admin')
        self.assertEqual(status, 503)
        self.assertNotIn('secret-token', json.dumps(body))

    def web_survey(self):
        return {'user_id': '8班_55_1', 'answers': survey(q3='B,C', q4='C')['answers']}

    def test_web_survey_submit_then_login_without_exposing_grades(self):
        body = self.web_survey()
        self.assertEqual(self.call('/questionnaire/status', body)[1], {'data': {'status': 'missing'}})
        status, result = self.call('/questionnaire/submit', body)
        self.assertEqual(status, 200)
        self.assertEqual(result, {'data': {'status': 'ready'}})
        self.assertEqual(self.call('/auth', {'user_id': body['user_id']})[0], 200)
        self.call('/questionnaire/submit', body)
        self.assertEqual(self.assessor.calls, 1)
        modified = self.web_survey()
        modified['answers']['q11'] = '我希望重写原来的结果'
        self.call('/questionnaire/submit', modified)
        saved = self.call('/admin/profile', {'class_no': 8, 'student_no': 55}, 'admin')[1]['data']
        self.assertEqual(saved['answers']['q11'], body['answers']['q11'])

    def test_web_survey_cannot_set_grades_or_overwrite_teacher_records(self):
        self.seed()
        body = self.web_survey() | {'P0': 3, 'Pn': 3, 'status': 'ready', 'replace_digest': 'anything'}
        body['answers']['q11'] = '我有艺术天赋'
        self.assertEqual(self.call('/questionnaire/submit', body)[1], {'data': {'status': 'ready'}})
        self.assertEqual(self.assessor.calls, 1)

    def test_web_survey_rejects_missing_or_conflicting_answers(self):
        for override in [{'q11': ''}, {'q3': 'A,B'}, {'q3': 'B,B'}, {'q4': 'E'}, {'q5': None}]:
            body = self.web_survey()
            body['answers'].update(override)
            self.assertEqual(self.call('/questionnaire/submit', body)[0], 422)
        self.assertFalse(self.store.data)

    def test_grader_failure_preserves_survey_and_allows_teacher_review(self):
        with patch.object(self.assessor, 'assess', side_effect=UpstreamError('temporary')):
            status, result = self.call('/questionnaire/submit', self.web_survey())
        self.assertEqual((status, result), (200, {'data': {'status': 'needs_review'}}))
        old = self.call('/admin/profile', {'class_no': 8, 'student_no': 55}, 'admin')[1]['data']
        self.assertEqual(self.call('/admin/review', {'class_no': 8, 'student_no': 55,
            'source_digest': old['source_digest'], 'assessment': assessment(confidence=1)}, 'admin')[0], 200)
        self.assertEqual(self.call('/questionnaire/status', self.web_survey())[1], {'data': {'status': 'ready'}})

    def test_interrupted_grading_is_recoverable_without_repeated_model_calls(self):
        q = Questionnaire.parse(survey(q3='B', q4='C'))
        self.store.create('submissions', self.app.learner_key('8', '55'),
            {'class_no': '8', 'student_no': '55', 'answers': q.answers, 'source_digest': q.digest, 'submitted_at': self.now})
        self.assertEqual(self.call('/questionnaire/submit', self.web_survey())[1]['data']['status'], 'processing')
        self.now += 121
        self.assertEqual(self.call('/questionnaire/status', self.web_survey())[1]['data']['status'], 'needs_review')
        self.assertEqual(self.call('/admin/profile', {'class_no': 8, 'student_no': 55}, 'admin')[0], 200)
        self.assertEqual(self.assessor.calls, 0)

    def test_teacher_can_retry_ai_without_manually_classifying_open_answer(self):
        with patch.object(self.assessor, 'assess', side_effect=UpstreamError('temporary')):
            self.call('/questionnaire/submit', self.web_survey())
        old = self.call('/admin/profile', {'class_no': 8, 'student_no': 55}, 'admin')[1]['data']
        self.assertEqual(self.call('/admin/regrade', {'class_no': 8, 'student_no': 55,
            'source_digest': 'stale'}, 'admin')[0], 409)
        status, result = self.call('/admin/regrade', {'class_no': 8, 'student_no': 55,
            'source_digest': old['source_digest']}, 'admin')
        self.assertEqual(status, 200)
        self.assertEqual(result['data']['status'], 'ready')
        self.assertEqual(self.call('/admin/regrade', {}, None)[0], 401)

    def test_variables_are_initialized_once_and_never_replaced_on_token_refresh(self):
        from unittest.mock import Mock
        self.app.variable_writer = Mock()
        self.seed()
        result = self.call('/auth', {'user_id': '8班_55_1'})[1]['data']
        self.app.variable_writer.initialize.assert_called_once()
        self.assertEqual(self.app.variable_writer.initialize.call_args.args[1], 3)
        self.call('/auth', {'user_id': '8班_55_1', 'profile_ref': result['profile_ref']})
        self.app.variable_writer.initialize.assert_called_once()

    def test_variable_initialization_failure_does_not_launch_unpersonalized_bot(self):
        from unittest.mock import Mock
        self.app.variable_writer = Mock()
        self.app.variable_writer.initialize.side_effect = UpstreamError('not authorized')
        self.seed()
        self.assertEqual(self.call('/auth', {'user_id': '8班_55_1'})[0], 502)
        self.assertFalse(any(key[0] == 'tickets' for key in self.store.data))


class LegacyCompatibilityTests(unittest.TestCase):
    def variables(self, pn):
        return {'P0': '0', 'Pn': str(pn), 'L0': '1', 'Ln': '1', 'K0': '1', 'Kn': '1'}

    def decisions(self, *accepted):
        targets = {'anthropomorphic': 1, 'retrieval': 2, 'pattern_generation': 3}
        return {'source': 'coze_semantic_dimensions', 'decisions': {
            key: self.variables(value if key in accepted else 0) for key, value in targets.items()}}

    def test_ai_semantics_do_not_require_keywords_and_do_not_invent_confidence(self):
        q = Questionnaire.parse(survey('不是翻照片，而是把见过的东西理解后创造没见过的作品。'))
        result = score_semantic(q, self.decisions('pattern_generation'))
        self.assertEqual((result['status'], result['total'], result['preconception']), ('ready', 100, 'P3'))
        self.assertIsNone(result['assessment']['confidence'])
        self.assertNotIn('Ln', result)

    def test_ai_handles_mixed_retrieval_and_unscorable_with_exact_rubric(self):
        cases = [('它很聪明，会去网上找。', ('anthropomorphic', 'retrieval'), 30),
                 ('AI学了很多，然后从里面找一张。', ('retrieval',), 40),
                 ('我不知道。', (), None)]
        for text, accepted, expected in cases:
            result = score_semantic(Questionnaire.parse(survey(text)), self.decisions(*accepted))
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(result['open_points'], expected)

    def test_protocol_failure_cannot_silently_turn_into_a_score(self):
        for field, value in [('Pn', 3), ('P0', 2), ('Ln', 4)]:
            result = self.decisions()
            result['decisions']['retrieval'][field] = value
            with self.assertRaises(ValidationError):
                score_semantic(Questionnaire.parse(survey()), result)

    def test_all_nonempty_open_answers_are_sent_to_ai(self):
        from backend.profiles.scoring import needs_model
        for text in ('不知道', '说不清', '它很聪明。'):
            self.assertTrue(needs_model(Questionnaire.parse(survey(text))))
        self.assertFalse(needs_model(Questionnaire.parse(survey(''))))

    def test_variable_api_reads_writes_and_verifies_existing_pn_only(self):
        writer = CozeVariableWriter()
        with patch.object(writer, 'request', side_effect=[
            {'data': {'items': [{'keyword': 'Pn', 'value': '0'}]}}, {'code': 0},
            {'data': {'items': [{'keyword': 'Pn', 'value': '2'}]}}
        ]) as request:
            writer.initialize({'token': 'secret', 'user_id_hash': 'safe'}, 2)
        body = request.call_args_list[1].args[2]
        self.assertEqual(body['connector_id'], '999')
        self.assertEqual(body['data'], [{'keyword': 'Pn', 'value': '2'}])
        self.assertEqual(body['connector_uid'], 'safe')

    def test_variable_name_in_prompt_is_not_treated_as_declared_variable(self):
        writer = CozeVariableWriter()
        with patch.object(writer, 'request', return_value={'data': {'items': []}}) as request:
            with self.assertRaises(UpstreamError):
                writer.initialize({'token': 'secret', 'user_id_hash': 'safe'}, 2)
        self.assertEqual(request.call_count, 1)


class CozeTests(unittest.TestCase):
    def stream(self, events):
        result = io.BytesIO(''.join('event: ' + kind + '\ndata: ' + json.dumps(item) + '\n\n' for kind, item in events).encode())
        result.headers = {'Content-Type': 'text/event-stream'}
        return result

    def test_assessment_stream_and_minimum_data_sent(self):
        events = [('conversation.message.completed', {'role': 'assistant', 'type': 'answer', 'content': json.dumps(assessment())}),
                  ('conversation.chat.completed', {'status': 'completed'})]
        with patch('urllib.request.urlopen', return_value=self.stream(events)) as request:
            self.assertEqual(CozeAssessor('secret').assess_dimension(Questionnaire.parse(survey()), 'pattern_generation'), assessment())
        body = json.loads(request.call_args.args[0].data)
        self.assertFalse(body['auto_save_history'])
        sent = json.loads(body['additional_messages'][0]['content'])
        self.assertEqual(set(sent), {'task', 'rubric_version', 'dimension', 'instructions', 'q11', 'q6_reference_only'})

    def test_single_json_code_fence_is_supported_but_prose_is_not(self):
        events = [('conversation.message.completed', {'role': 'assistant', 'type': 'answer',
            'content': '```json\n' + json.dumps(assessment()) + '\n```'}), ('conversation.chat.completed', {})]
        with patch('urllib.request.urlopen', return_value=self.stream(events)):
            self.assertEqual(CozeAssessor('secret').assess_dimension(Questionnaire.parse(survey()), 'retrieval'), assessment())

    def test_repeated_identical_json_is_deduplicated_but_conflicts_fail(self):
        first = json.dumps(assessment())
        for second, valid in [(first, True), (json.dumps(assessment(category='retrieval')), False)]:
            events = [('conversation.message.completed', {'role': 'assistant', 'type': 'answer',
                'content': first + '\n' + second}), ('conversation.chat.completed', {})]
            with patch('urllib.request.urlopen', return_value=self.stream(events)):
                if valid:
                    self.assertEqual(CozeAssessor('secret').assess_dimension(Questionnaire.parse(survey()), 'retrieval'), assessment())
                else:
                    with self.assertRaises(ValidationError):
                        CozeAssessor('secret').assess_dimension(Questionnaire.parse(survey()), 'retrieval')

    def test_hidden_ai_judges_all_dimensions_in_isolated_contexts(self):
        assessor = CozeAssessor('secret')
        with patch.object(assessor, 'assess_dimension', side_effect=lambda q, name: name) as request:
            result = assessor.assess(Questionnaire.parse(survey('我不知道')))
        self.assertEqual(set(result['decisions']), {'anthropomorphic', 'retrieval', 'pattern_generation'})
        self.assertEqual(request.call_count, 3)

    def test_failed_or_truncated_stream_never_becomes_a_grade(self):
        for events in [[('conversation.chat.failed', {'last_error': 'quota'})],
                       [('conversation.message.completed', {'role': 'assistant', 'type': 'answer', 'content': '{}'})]]:
            with patch('urllib.request.urlopen', return_value=self.stream(events)), self.assertRaises(UpstreamError):
                CozeAssessor('secret').assess_dimension(Questionnaire.parse(survey()), 'pattern_generation')

    def test_existing_oauth_is_reused_without_a_persistent_coze_secret(self):
        issuer = FakeAuth()
        events = [('conversation.message.completed', {'role': 'assistant', 'type': 'answer', 'content': json.dumps(assessment())}),
                  ('conversation.chat.completed', {})]
        with patch('urllib.request.urlopen', return_value=self.stream(events)) as request:
            CozeAssessor(token_provider=issuer).assess_dimension(Questionnaire.parse(survey()), 'pattern_generation')
        self.assertEqual(issuer.calls, 1)
        self.assertEqual(json.loads(request.call_args.args[0].data)['user_id'], 'stable-hashed-id')
        self.assertEqual(request.call_args.args[0].get_header('Authorization'), 'Bearer fresh-token-1')

    def test_markdown_response_requires_review(self):
        events = [('conversation.message.completed', {'role': 'assistant', 'type': 'answer', 'content': '说明文字：```json\n{}\n```'}),
                  ('conversation.chat.completed', {})]
        with patch('urllib.request.urlopen', return_value=self.stream(events)), self.assertRaises(ValidationError):
            CozeAssessor('secret').assess_dimension(Questionnaire.parse(survey()), 'pattern_generation')


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'survey.xlsx'

    def workbook(self, rows, headers=FIELDS):
        from openpyxl import Workbook
        book = Workbook()
        book.active.append(headers)
        for row in rows: book.active.append(row)
        book.save(self.path)

    def row(self):
        value = survey()
        return [value['class_no'], value['student_no']] + [value['answers'].get(key, '') for key in FIELDS[2:]]

    def test_template_and_read(self):
        write_template(self.path)
        from openpyxl import load_workbook
        book = load_workbook(self.path)
        book.active.append(self.row())
        book.save(self.path)
        book.close()
        result = read_xlsx(self.path)
        self.assertEqual(result[0]['class_no'], '8')
        self.assertEqual(result[0]['answers']['q9'], 'B')

    def test_duplicate_identity_rejected_before_import(self):
        self.workbook([self.row(), self.row()])
        with self.assertRaisesRegex(ValidationError, '重复'):
            read_xlsx(self.path)

    def test_formulas_and_missing_columns_rejected(self):
        row = self.row()
        row[-2] = '=1+1'
        self.workbook([row])
        with self.assertRaisesRegex(ValidationError, '公式'):
            read_xlsx(self.path)
        self.workbook([self.row()[:-2]], FIELDS[:-2])
        with self.assertRaisesRegex(ValidationError, '缺少列'):
            read_xlsx(self.path)


if __name__ == '__main__':
    unittest.main()
