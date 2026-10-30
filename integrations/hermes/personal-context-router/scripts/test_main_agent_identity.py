#!/usr/bin/env python3
"""Synthetic native registration -> middleware -> hooks -> writer, network forbidden.

Run in the existing Hermes dependency interpreter with the host checkout on sys.path.
No provider inference, real identities or live memory writes are used.
"""
from __future__ import annotations
import importlib
import json
import os
from pathlib import Path
import sys
import time
import tempfile
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
sys.dont_write_bytecode = True
_IMPORT_HOME = tempfile.TemporaryDirectory(prefix='pcr-native-import-', dir=os.environ.get('TMPDIR'))
os.environ['HERMES_HOME'] = _IMPORT_HOME.name
sys.path.insert(0, str(Path(__file__).parent))
import identity_test_fixtures as old
from hermes_cli.plugins import PluginContext, PluginManifest, PluginManager
import hermes_cli.plugins as host
from hermes_cli.middleware import run_tool_execution_middleware


class Transport(old.FakeMemoryTransport):
    def card(self, eid):
        card = super().card(eid)
        if eid != 'person-self':
            card['relationship_edges'].append({'id': 'hint-'+eid, 'status':'active',
                'from_entity_id':'person-self', 'to_entity_id':eid, 'claim_text':'사용자의 프로젝트 동료',
                'claim_basis':'reported', 'confidence':0.9})
        return card

    def __call__(self, config, method, path, payload=None):
        route, q = urlsplit(path).path, parse_qs(urlsplit(path).query)
        if method == 'GET' and route in {'/api/entities', '/api/memories'}:
            self.calls.append((method,path,deepcopy(payload)))
            rows = [] if route == '/api/memories' else list(self.entities.values())
            if 'system_role' in q:
                rows = [r for r in rows if r.get('system_role') == q['system_role'][0]]
            if 'q' in q:
                rows = [r for r in rows if q['q'][0].lower() in r['display_name'].lower()]
            offset, limit = int(q.get('offset',[0])[0]), int(q.get('limit',[100])[0])
            return {'items':deepcopy(rows[offset:offset+limit]),'total':len(rows)}
        if method == 'POST' and route == '/api/entities/resolve':
            rows = [r for r in self.entities.values() if payload['surface'].lower() == r['display_name'].lower()]
            return {'ambiguity':'single_strong_match' if len(rows)==1 else 'no_match' if not rows else 'multiple_close_matches',
                    'matches':[{'entity_id':r['id'],'entity_type':'person'} for r in rows]}
        return super().__call__(config, method, path, payload)


class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        old.SaveFirstMemoryTests.setUpClass.__func__(cls)
        cls.identity = importlib.import_module(old.smoke.PLUGIN_MODULE_NAME+'.router.identity')
        cls.hooks = importlib.import_module(old.smoke.PLUGIN_MODULE_NAME+'.router.hooks')

    def setUp(self):
        old.SaveFirstMemoryTests.setUp(self)
        self.transport = Transport()
        self.transport.entities['harin'] = {'id':'harin','display_name':'김하린','entity_type':'person','status':'active'}
        self.claim = old.observation(subject='하린이', content='하린이는 간결한 답장을 좋아한다', source_quote='하린이는 간결한 답장을 좋아해')
        self.human = self.claim['source_quote']
        self.native = {'session_id':'native-session','turn_id':'turn-a','sender_id':'fixture-owner','platform':'discord',
                       'user_message':self.human,'conversation_history':[{'role':'user','content':'프로젝트 동료 김하린을 하린이라고 불러.'},
                                                                        {'role':'user','content':self.human}]}
        self.claims = [self.claim]
        parsed = {**old.smoke.relationship_classifier(''), 'should_record':True, 'subjects':['하린이'],
                  'post_turn_target':'relationships','evidence_summary':'Current human only.', 'kinlayer_memories':self.claims}
        self.parsed = parsed
        self.router = self.hooks.PersonalContextRouter(config_loader=lambda:self.config,
            plugin_llm=SimpleNamespace(complete_structured=lambda **kw: (_ for _ in ()).throw(AssertionError('aux identity inference forbidden'))),
            manifest_loader=old.smoke.StaticManifestLoader(old.smoke.test_manifest_bundle(Path(self.home.name))),
            dimension_classifier=lambda text: parsed, synchronous_post_turn=True)
        self.addCleanup(self.router.shutdown)
        self.module = sys.modules[old.smoke.PLUGIN_MODULE_NAME]
        self.manager = PluginManager()
        self.manager._discovered = True  # Admit only this fixture plugin; no unrelated built-ins.
        ctx = PluginContext(PluginManifest(name='personal-context-router',path=str(old.smoke.PLUGIN_ROOT)),self.manager)
        ctx._llm = self.router._plugin_llm
        # Use actual host hook/middleware registrars and profile-local tool registry.
        for target, attr, value in [(self.module,'get_router',lambda:self.router),(self.post,'_kinlayer_request',self.transport),
                                   (host,'get_plugin_manager',lambda:self.manager)]:
            guard=patch.object(target,attr,value); guard.start(); self.addCleanup(guard.stop)
        self.module.register(ctx)
        self.open()

    def open(self, **updates):
        self.native.update(updates)
        self.manager.invoke_hook('pre_llm_call',**self.native)

    def tool(self, args, **binding):
        ids = {'session_id':self.native['session_id'],'turn_id':self.native['turn_id'],'tool_call_id':'call-fixture',**binding}
        from tools.registry import registry
        value = run_tool_execution_middleware('kinlayer_identity', args,
            lambda p:registry.dispatch('kinlayer_identity',p,session_id=ids['session_id']), **ids)
        return json.loads(value)

    def lookup(self, surface='하린이'):
        return self.tool({'action':'lookup','surface':surface,'hint_queries':[]})

    def decide(self, lookup=None, **updates):
        lookup = lookup or self.lookup()
        p = {'action':'decide','lookup_token':lookup['lookup_token'],'candidate_id':'harin',
             'evidence_refs':['entities:harin'],'context_quotes':['프로젝트 동료 김하린을 하린이라고 불러.'],
             'excluded_candidate_ids':[], 'reason':'Current conversational referent is the project colleague; spelling is not identity authority.', **updates}
        return self.tool(p)

    def finish(self):
        self.manager.invoke_hook('post_llm_call',**{k:v for k,v in self.native.items() if k!='sender_id'},assistant_response='알겠어요.')

    def test_variant_native_writer_source_and_once(self):
        self.assertTrue(self.decide()['ok'])
        self.finish(); self.finish()
        self.assertEqual(len(self.transport.memory_calls),1)
        body=self.transport.memory_calls[0]
        self.assertEqual(body['record']['payload']['subject_entity_id'],'harin')
        self.assertEqual(body['source']['excerpt'],self.human)
        self.assertEqual(body['source']['actor'],'user')
        self.assertNotIn('프로젝트 동료',body['source']['excerpt'])

    def test_lookup_does_not_decide_or_mutate(self):
        result=self.lookup()
        self.assertEqual(result['status'],'clarification_needed')
        self.assertFalse(result['write_authorized']); self.finish()
        self.assertEqual(self.transport.memory_calls,[])

    def test_missing_decision_blocks_without_question_or_creation(self):
        self.finish()
        self.assertEqual(self.transport.memory_calls,[])
        self.assertFalse([c for c in self.transport.calls if c[0]=='POST' and c[1]=='/api/entities'])
        self.assertIsNone(self.router.transform_llm_output(response_text='좋아요.',session_id='native-session',turn_id='turn-a'))

    def test_unfamiliar_variant_no_string_gate(self):
        self.native['user_message']='코드네임 파랑새는 간결한 답장을 좋아해'
        self.native['conversation_history']=[{'role':'user','content':'프로젝트 동료 김하린의 코드네임은 파랑새야.'}]
        self.open(turn_id='turn-unfamiliar')
        # Agent may search canonical name established in its actual context.
        self.claim.update(subject='파랑새', content='파랑새는 간결한 답장을 좋아한다', source_quote=self.native['user_message'])
        self.parsed['subjects']=['파랑새']
        lookup=self.tool({'action':'lookup','surface':'파랑새','hint_queries':['김하린']})
        self.assertTrue(self.decide(lookup,context_quotes=['프로젝트 동료 김하린의 코드네임은 파랑새야.'])['ok'])
        self.finish()
        self.assertEqual(len(self.transport.memory_calls),1)
        self.assertEqual(self.transport.memory_calls[0]['record']['payload']['subject_entity_id'],'harin')

    def test_forged_candidate_fails(self):
        self.assertFalse(self.decide(candidate_id='invented')['ok']); self.finish()
        self.assertFalse(self.transport.memory_calls)

    def test_forged_reference_fails(self):
        self.assertFalse(self.decide(evidence_refs=['entity_edges:invented'])['ok'])

    def test_forged_context_fails(self):
        self.assertFalse(self.decide(context_quotes=['invented human claim'])['ok'])

    def test_caller_cannot_supply_binding(self):
        self.assertFalse(self.tool({'action':'status','turn_id':'turn-a'})['ok'])
        self.assertFalse(json.loads(self.module._identity_tool({'action':'status'},session_id='native-session'))['ok'])

    def test_cross_turn_and_session_token_fails(self):
        lookup=self.lookup(); self.open(turn_id='turn-b')
        self.assertFalse(self.decide(lookup)['ok'])
        self.assertFalse(self.tool({'action':'lookup','surface':'하린이'},session_id='another-session')['ok'])

    def test_sender_collision_revokes(self):
        self.decide(); self.open(sender_id='other-sender'); self.finish()
        self.assertFalse(self.transport.memory_calls)

    def test_changed_human_same_turn_revokes(self):
        self.decide(); self.open(user_message='아니 다른 하린이야'); self.finish()
        self.assertFalse(self.transport.memory_calls)

    def test_changed_referent_next_turn_needs_new_decision(self):
        self.decide(); self.finish()
        self.open(turn_id='turn-b',user_message='아니 다른 하린이는 간결한 답장을 좋아해')
        self.finish(); self.assertEqual(len(self.transport.memory_calls),1)

    def test_expired_frame_rejected(self):
        lookup=self.lookup()
        for frame in self.router._identity_state.turns.values(): frame['created']-=self.identity.SESSION_TTL+1
        self.assertFalse(self.decide(lookup)['ok'])

    def test_lookup_failure_no_question(self):
        with patch.object(self.post,'_kinlayer_request',side_effect=ConnectionError('offline')):
            result=self.lookup(); self.assertFalse(result['ok']); self.assertIsNone(result['question'])
        self.assertFalse(self.decide(result)['ok'])

    def test_changed_card_rejected(self):
        lookup=self.lookup(); self.transport.entities['harin']['display_name']='다른 표시명'
        self.assertEqual(self.decide(lookup)['reason'],'candidate_snapshot_stale')

    def test_multiple_candidates_need_explicit_exclusion(self):
        self.transport.entities['harin2']={'id':'harin2','display_name':'이하린','entity_type':'person','status':'active'}
        lookup=self.lookup()
        self.assertFalse(self.decide(lookup)['ok'])
        self.assertTrue(self.decide(lookup,excluded_candidate_ids=['harin2'])['ok'])

    def test_unresolved_remains_agent_choice(self):
        lookup=self.lookup(); self.tool({'action':'unresolved','lookup_token':lookup['lookup_token']})
        self.finish(); self.assertFalse(self.transport.memory_calls)

    def test_signed_handoff_forgery_and_scope(self):
        self.decide(); handoff=self.router._identity_state.post(self.config,None,self.native)
        kwargs={**self.native,**handoff}
        self.assertTrue(self.identity.validated_results(self.config,kwargs,self.human))
        for field,value in [('session_id','foreign'),('turn_id','foreign'),('_identity_proof','forged')]:
            self.assertFalse(self.identity.validated_results(self.config,{**kwargs,field:value},self.human))
        forged=deepcopy(kwargs); forged['_identity_results']['하린이']['entity_id']='invented'
        self.assertFalse(self.identity.validated_results(self.config,forged,self.human))
        self.assertFalse(self.identity.validated_results(self.config,kwargs,'tool text'))
        config=deepcopy(self.config); config.kinlayer.base_url='http://other.invalid'
        self.assertFalse(self.identity.validated_results(config,kwargs,self.human))
        from hermes_constants import set_hermes_home_override,reset_hermes_home_override
        token=set_hermes_home_override(Path(self.home.name)/'other-profile')
        try: self.assertFalse(self.identity.validated_results(self.config,kwargs,self.human))
        finally: reset_hermes_home_override(token)

    def test_legacy_deferred_rows_preserved_not_replayed(self):
        with self.post._memory_journal(self.config) as db:
            db.execute('INSERT INTO identity_deferred VALUES (?,?,?,?)',('legacy','input','{"synthetic":"old claim"}',0))
            db.execute('INSERT INTO identity_pending VALUES (?,?,?,?,?)',('legacy','backend','name','{"synthetic":true}',0)); db.commit()
        self.decide(); self.finish()
        with self.post._memory_journal(self.config) as db:
            self.assertEqual(db.execute('SELECT payload FROM identity_deferred').fetchall(),[('{"synthetic":"old claim"}',)])
            self.assertEqual(db.execute('SELECT payload FROM identity_pending').fetchall(),[('{"synthetic":true}',)])
        self.assertEqual(len(self.transport.memory_calls),1)

    def test_decide_accepts_matching_surface_echo(self):
        # Regression: models often echo the lookup surface into decide.
        self.assertTrue(self.decide(surface='하린이')['ok']); self.finish()
        self.assertEqual(len(self.transport.memory_calls),1)

    def test_decide_surface_mismatch_rejected_without_state_change(self):
        lookup=self.lookup()
        r=self.decide(lookup,surface='다른이름')
        self.assertEqual(r['reason'],'surface_mismatch'); self.assertFalse(r['write_authorized'])
        # The mismatched call recorded nothing; a correct decision still succeeds.
        self.assertTrue(self.decide(lookup)['ok']); self.finish()
        self.assertEqual(len(self.transport.memory_calls),1)

    def test_unresolved_accepts_matching_surface_echo(self):
        lookup=self.lookup()
        self.assertTrue(self.tool({'action':'unresolved','surface':'하린이','lookup_token':lookup['lookup_token']})['ok'])
        self.finish(); self.assertFalse(self.transport.memory_calls)

    def test_invalid_arguments_names_unexpected_fields(self):
        r=self.decide(session_id='forged')
        self.assertEqual(r['reason'],'invalid_arguments'); self.assertEqual(r['unexpected_fields'],['session_id'])
        r=self.tool({'action':'status','surface':'하린이'})
        self.assertEqual(r['unexpected_fields'],['surface'])
        self.assertTrue(self.tool({'action':'bogus'})['invalid_action'])
        self.finish(); self.assertFalse(self.transport.memory_calls)

    def test_status_has_no_backend_or_write(self):
        before=len(self.transport.calls)
        r=self.tool({'action':'status'})
        self.assertTrue(r['native_turn_bound']); self.assertEqual(r['writes'],0)
        self.assertEqual(len(self.transport.calls),before)

    def test_subagent_cannot_establish_frame(self):
        self.open(turn_id='child',parent_session_id='native-session')
        self.assertFalse(self.lookup()['ok'])

    def test_synthetic_user_has_no_frame(self):
        self.open(turn_id='synthetic',user_message='[IMPORTANT: You are running as a scheduled cron job. fixture]')
        self.assertFalse(self.lookup()['ok'])
        probe=self.tool({'action':'status'})
        self.assertTrue(probe['ok']); self.assertFalse(probe['decision_frame_admitted'])

    def test_writer_never_expands_spelling_over_unresolved(self):
        self.native['user_message']='하린씨와 하린이는 서로 다른 사람이고 하린은 간결한 답장을 좋아해'
        self.open(turn_id='distinct')
        self.claim.update(subject='하린',source_quote=self.native['user_message'])
        a=self.lookup('하린씨'); self.assertTrue(self.decide(a)['ok'])
        b=self.lookup('하린이'); self.tool({'action':'unresolved','lookup_token':b['lookup_token']})
        self.finish(); self.assertFalse(self.transport.memory_calls)

    def test_natural_bonin_is_not_owner_without_decision(self):
        self.native['user_message']='하린이는 본인이 간결한 답장을 좋아한다고 했어'
        self.claim.update(subject='본인',source_quote=self.native['user_message'])
        self.open(turn_id='third-person-self'); self.finish()
        self.assertFalse(self.transport.memory_calls)

    def test_conflict_latch_survives_unresolved(self):
        self.transport.entities['harin2']={'id':'harin2','display_name':'이하린','entity_type':'person','status':'active'}
        lookup=self.lookup()
        self.assertTrue(self.decide(lookup,excluded_candidate_ids=['harin2'])['ok'])
        self.assertFalse(self.decide(lookup,candidate_id='harin2',excluded_candidate_ids=['harin'])['ok'])
        self.tool({'action':'unresolved','lookup_token':lookup['lookup_token']})
        self.assertFalse(self.decide(lookup,candidate_id='harin2',excluded_candidate_ids=['harin'])['ok'])
        self.finish(); self.assertFalse(self.transport.memory_calls)

    def test_explicit_main_agent_mention_map_only(self):
        self.assertTrue(self.decide(mention_surfaces=['하린이','하린'])['ok'])
        self.claim['subject']='하린'
        self.finish(); self.assertEqual(len(self.transport.memory_calls),1)

    def test_async_worker_pins_home_despite_environment_change(self):
        import threading
        entered, release, done=threading.Event(), threading.Event(), threading.Event()
        original=self.router._run_post_turn_scoped
        def worker(job):
            entered.set(); release.wait(5)
            try: return original(job)
            finally: done.set()
        self.router._synchronous_post_turn=False
        with patch.object(self.router,'_run_post_turn_scoped',side_effect=worker):
            self.decide(); self.finish()
            self.assertTrue(entered.wait(5))
            with patch.dict(os.environ,{'HERMES_HOME':str(Path(self.home.name)/'foreign-profile')}):
                release.set(); self.assertTrue(done.wait(5))
        self.assertEqual(len(self.transport.memory_calls),1)
        self.assertFalse((Path(self.home.name)/'foreign-profile').exists())

    def test_writer_revalidates_archived_candidate(self):
        self.decide(); self.transport.entities['harin']['status']='deleted'
        self.finish(); self.assertFalse(self.transport.memory_calls)

    def test_old_or_tool_quote_cannot_become_current_human_source(self):
        self.decide(); self.claim['source_quote']='프로젝트 동료 김하린을 하린이라고 불러.'
        self.finish(); self.assertFalse(self.transport.memory_calls)

    def test_native_sender_label_not_person_evidence(self):
        self.assertEqual(self.post._usable_person_subjects(['Fixture owner'],'[Fixture owner] hello'),[])
        self.assertEqual(self.post._usable_person_subjects(['Fixture owner'],'[Fixture owner] Fixture owner is a colleague'),['Fixture owner'])

    def test_inactive_legacy_route_remains_fail_closed(self):
        from importlib import import_module
        recon=import_module(old.smoke.PLUGIN_MODULE_NAME+'.router.reconciliation')
        self.config.kinlayer.reconciliation.mode='bridge'
        self.config.kinlayer.reconciliation.guild_id='100'
        self.config.kinlayer.reconciliation.channel_id='200'
        self.config.kinlayer.reconciliation.owner_ids=('300',)
        self.config.kinlayer.reconciliation.reconciliation_parent_channel_id='200'
        with self.assertRaises(recon.ReconciliationError): recon._enabled(self.config)
        self.config.kinlayer.reconciliation.approved_guild_id='100'
        self.config.kinlayer.reconciliation.approved_channel_id='200'
        self.assertIs(recon._enabled(self.config),self.config.kinlayer.reconciliation)
        self.config.kinlayer.reconciliation.guild_id='101'
        with self.assertRaises(recon.ReconciliationError): recon._enabled(self.config)

if __name__=='__main__': unittest.main(verbosity=2)
