"""Scripture parsing, exact source fidelity and persistent editorial controls."""
import copy
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from scripture import Scripture, TextRuns, strip_markers, save_manifest, load_manifest, digest, canonical
from markdown import generate_markdown

AID = '00000000-0000-4000-8000-000000000010'

def article(source):
    return {'id':AID, 'html':source}

class ScriptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.overrides = self.root/'overrides.json'
        self.overrides.write_text('{"schema_version":1,"articles":{}}')

    def tearDown(self):
        self.temp.cleanup()

    def scanner(self):
        return Scripture(ledger=self.root/'initial.json',cache=self.root/'cache.json',overrides=self.overrides)

    def scan(self, source, locale='en'):
        scanner = self.scanner()
        item = article(source)
        scanner.prepare({locale:[item]})
        return scanner,item,scanner.render(locale,item)

    def rules(self, rules):
        self.overrides.write_text(json.dumps({'schema_version':1,'articles':{'en:'+AID:rules}}))

    def test_split_emphasis_entities_emoji_and_exact_roundtrip(self):
        source = '<article><p>😀 &amp; See <em>John</em> 3:16–18 &amp; Genesis 1:1.</p></article>'
        scanner,item,result = self.scan(source)
        self.assertEqual(strip_markers(result),source)
        self.assertEqual(item['html'],source)
        self.assertIn('data-reference="43 3:16-18"',result)
        self.assertIn('data-reference="1 1:1"',result)
        self.assertGreater(result.count('data-reference="43 3:16-18"'),1)
        self.assertEqual(result.count('data-bible-url="https://trueChristian.church/scriptures/"'),result.count('class="scripture-reference"'))
        self.assertNotIn('tabindex=',result)
        self.assertIn('&amp;', result)
        self.assertEqual(scanner.report['rendered'],2)

    def test_all_21_languages_and_unicode_digits(self):
        fixtures = {'en':'John 3:16','af':'Johannes 3:16','ar':'يوحنا ٣:١٦','bn':'যোহন ৩:১৬','de':'Johannes 3,16','el':'Ιωάννης 3:16','es':'Juan 3:16','fr':'Jean 3:16','he':'יוחנן 3:16','hi':'यूहन्ना ३:१६','id':'Yohanes 3:16','it':'Giovanni 3:16','ko':'요한복음 3:16','nb':'Johannes 3:16','nl':'Johannes 3:16','pt':'João 3:16','ru':'Иоанна 3:16','sv':'Johannes 3:16','sw':'Yohana 3:16','ur':'یوحنا ۳:۱۶','zh-Hans':'约翰福音3:16'}
        scanner=self.scanner()
        items={tag:[article('<p>'+text+'</p>')] for tag,text in fixtures.items()}
        scanner.prepare(items)
        for tag,values in items.items():
            with self.subTest(locale=tag):
                record=scanner.current[(tag,AID)]
                self.assertEqual(record['markers'][0]['queries'],['43 3:16'])
                output=scanner.render(tag,values[0])
                self.assertEqual(strip_markers(output),values[0]['html'])
                self.assertEqual('scripture-reference' in output,tag not in {'bn','hi','id','sw','ur'})
                self.assertEqual(output.count('data-bible-url="https://trueChristian.church/scriptures/"'),output.count('class="scripture-reference"'))

    def test_numbered_books_chapter_only_and_cross_chapter(self):
        scanner,item,result=self.scan('<p>1 Corinthians 13:4–7; John 3:36–4:2; Psalm 23.</p>')
        queries=[m['queries'] for m in scanner.current[('en',AID)]['markers']]
        self.assertIn(['46 13:4-7'],queries)
        self.assertIn(['43 3:36','43 4:1-2'],queries)
        self.assertIn(['19 23:1-6'],queries)

    def test_links_code_notices_times_and_bare_verses_are_untouched(self):
        source='<article><p>At 3:16 am, verse 16, Is 3:4, Ph 2:3, John 99:99 and John 3:999.</p><p><a href="/">John 3:16</a><code>John 3:16</code></p><pre>John 3:16</pre><script>"John 3:16"</script></article><aside data-translation-notice="ai"><p>John 3:16</p></aside>'
        scanner,item,result=self.scan(source)
        self.assertEqual(result,source)

    def test_safe_abbreviations_roman_numbered_books_and_partial_verses(self):
        scanner,item,result=self.scan('<p>Jn 3:16; Ps 23; I John 4:1. Luke 9:43b–45.</p>')
        queries=[m['queries'] for m in scanner.current[('en',AID)]['markers']]
        self.assertIn(['43 3:16'],queries)
        self.assertIn(['19 23:1-6'],queries)
        self.assertIn(['62 4:1'],queries)
        self.assertNotIn('42 9:',result)

    def test_does_not_cross_blocks_or_skipped_subtrees(self):
        _,_,result=self.scan('<p>John</p><p>3:16</p><p>John <a href="/">source</a> 3:16</p>')
        self.assertNotIn('scripture-reference',result)

    def test_cached_unchanged_never_invokes_detector(self):
        scanner,item,result=self.scan('<p>John 3:16</p>')
        save_manifest(self.root/'cache.json',scanner.records)
        reused=self.scanner()
        with patch('scripture.subprocess.run',side_effect=AssertionError('unnecessary scan')):
            reused.prepare({'en':[item]})
            self.assertEqual(reused.render('en',item),result)
        self.assertEqual(reused.report['reused'],1)
        self.assertEqual(reused.report['scanned'],0)

    def test_only_changed_article_is_rescanned(self):
        scanner,item,result=self.scan('<p>John 3:16</p>')
        save_manifest(self.root/'cache.json',scanner.records)
        second=article('<p>Romans 8:1</p>'); second['id']='00000000-0000-4000-8000-000000000011'
        reused=self.scanner(); reused.prepare({'en':[item,second]})
        self.assertEqual(reused.report['reused'],1)
        self.assertEqual(reused.report['scanned'],1)

    def test_override_edit_rerenders_without_rescan(self):
        scanner,item,result=self.scan('<p>See John 3:16 today.</p>')
        marker=scanner.current[('en',AID)]['markers'][0]
        save_manifest(self.root/'cache.json',scanner.records)
        self.rules([{'action':'suppress','marker_id':marker['id'],'anchor':{k:marker[k] for k in ('quote','before','after')},'reason':'Editor correction'}])
        reused=self.scanner()
        with patch('scripture.subprocess.run',side_effect=AssertionError('unnecessary scan')):
            reused.prepare({'en':[item]})
            self.assertEqual(reused.render('en',item),item['html'])
        self.assertEqual(reused.report['suppressed'],1)

    def test_suppression_reanchors_unique_quote_context_after_source_edit(self):
        scanner,item,result=self.scan('<p>See John 3:16 today.</p>')
        marker=scanner.current[('en',AID)]['markers'][0]
        self.rules([{'action':'suppress','marker_id':marker['id'],'anchor':{k:marker[k] for k in ('quote','before','after')}}])
        _,_,output=self.scan('<p>New preface.</p>'+item['html'])
        self.assertNotIn('scripture-reference',output)

    def test_stale_suppression_fails_closed_and_is_reported(self):
        self.rules([{'action':'suppress','marker_id':'a'*24,'anchor':{'quote':'John 3:16','before':'Previous context','after':''}}])
        scanner,item,result=self.scan('<p>John 3:16 and Romans 8:1.</p>')
        self.assertEqual(result,item['html'])
        self.assertEqual(len(scanner.report['review_required']),1)

    def test_include_anchor_requires_unique_match(self):
        self.rules([{'action':'include','anchor':{'quote':'Jn III.16','before':'See ','after':'.'},'queries':['43 3:16']}])
        scanner,item,result=self.scan('<p>See Jn III.16.</p>')
        self.assertIn('data-reference="43 3:16"',result)
        self.assertEqual(strip_markers(result),item['html'])
        self.rules([{'action':'include','anchor':{'quote':'custom'},'queries':['43 3:16']}])
        scanner,item,result=self.scan('<p>custom and custom</p>')
        self.assertEqual(result,item['html'])
        self.assertEqual(len(scanner.report['review_required']),1)

    def test_include_corrects_queries_of_existing_marker(self):
        scanner,item,_=self.scan('<p>See John 3:16.</p>')
        marker=scanner.current[('en',AID)]['markers'][0]
        save_manifest(self.root/'cache.json',scanner.records)
        self.rules([{'action':'include','marker_id':marker['id'],'anchor':{k:marker[k] for k in ('quote','before','after')},'queries':['43 3:17']}])
        reused=self.scanner()
        with patch('scripture.subprocess.run',side_effect=AssertionError('unnecessary scan')):
            reused.prepare({'en':[item]})
            output=reused.render('en',item)
        self.assertIn('data-reference="43 3:17"',output)
        self.assertNotIn('data-reference="43 3:16"',output)

    def test_suppression_rejects_newly_expanded_match(self):
        self.rules([{'action':'suppress','marker_id':'a'*24,'anchor':{'quote':'John 3:16','before':'See ','after':''}}])
        _,_,output=self.scan('<p>See John 3:16,17.</p>')
        self.assertNotIn('scripture-reference',output)

    def test_ledger_integrity_rejects_edited_detection_records(self):
        scanner,_,_=self.scan('<p>John 3:16</p>')
        path=self.root/'cache.json'; save_manifest(path,scanner.records)
        value=json.loads(path.read_text()); next(iter(value['records'].values()))['markers'][0]['quote']='changed'
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError): load_manifest(path)

    def test_injected_queries_are_rejected(self):
        self.rules([{'action':'include','anchor':{'quote':'custom'},'queries':['https://evil.example/']}])
        with self.assertRaises(ValueError): self.scan('<p>custom</p>')

    def test_idempotence_of_text_extractor(self):
        _,_,result=self.scan('<p>John 3:16</p>')
        runs=TextRuns(result).runs
        self.assertFalse(any('John' in run['text'] for run in runs))

    def test_markdown_and_ai_notice_are_unchanged(self):
        notice='<aside data-translation-notice="ai"><p>AI notice John 3:16</p></aside>'
        item={'id':AID,'locale':'en','html':'<article><p>John&nbsp;3&#58;16</p></article>'+notice}
        before=generate_markdown(item,'https://example.test/article/','Issue')
        scanner=self.scanner(); scanner.prepare({'en':[item]})
        result=scanner.render('en',item)
        self.assertIn(notice,result)
        self.assertEqual(strip_markers(result),item['html'])
        self.assertEqual(generate_markdown(item,'https://example.test/article/','Issue'),before)

    def test_rendered_fragment_is_idempotent(self):
        _,_,once=self.scan('<p>John 3:16</p>')
        _,_,twice=self.scan(once)
        self.assertEqual(once,twice)

    def test_mixed_european_and_colon_punctuation(self):
        scanner,item,result=self.scan('<p>Jean 3,16 et Romains 8:1.</p>','fr')
        self.assertEqual([m['queries'] for m in scanner.current[('fr',AID)]['markers']],[['43 3:16'],['45 8:1']])

    def test_later_include_does_not_undo_unresolved_suppression(self):
        self.rules([{'action':'suppress','anchor':{'quote':'missing'}}, {'action':'include','anchor':{'quote':'John 3:16'},'queries':['43 3:16']}])
        scanner,item,result=self.scan('<p>John 3:16</p>')
        self.assertEqual(result,item['html'])
        self.assertEqual(len(scanner.report['review_required']),1)

    @unittest.skipUnless((ROOT/'.build/english/catalogue.json').is_file(), 'source exports unavailable')
    def test_full_published_corpus_reuses_cache_without_detection(self):
        from content import load_content
        model=load_content(ROOT/'.build/english',ROOT/'.build/translations',language_registry=ROOT/'.build/languages.json')
        first=Scripture(ledger=ROOT/'data/scripture-ledger',cache=self.root/'absent.json',overrides=self.overrides)
        first.prepare(model['articles'])
        save_manifest(self.root/'cache.json',first.records)
        second=self.scanner()
        with patch('scripture.subprocess.run',side_effect=AssertionError('unchanged corpus rescanned')):
            second.prepare(model['articles'])
        self.assertEqual(second.report['scanned'],0)
        self.assertEqual(second.report['reused'],sum(len(items) for items in model['articles'].values()))

    def test_static_map_all_locales_no_unapproved_fallback(self):
        mapping=json.loads((ROOT/'data/scripture-translations.json').read_text())
        ui=json.loads((ROOT/'data/scripture-ui.json').read_text())
        self.assertEqual(set(mapping['locales']),set(ui))
        self.assertEqual(len(ui),21)
        self.assertEqual(mapping['locales']['en']['abbreviation'],'kjv')
        for locale in ['bn','hi','id','sw','ur']:
            self.assertIsNone(mapping['locales'][locale]['abbreviation'])
        for locale,value in mapping['locales'].items():
            if value['abbreviation']:
                self.assertTrue(value['core_66_verified'])
                self.assertGreaterEqual(value['book_count'],66)
