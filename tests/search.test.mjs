import test from 'node:test';
import assert from 'node:assert/strict';
import { normalize, tokenize, prepare, search, preferredLocale } from '../assets/search-core.js';
const records=prepare([
 {id:'one',title:'Grace in everyday life',body:'A patient servant learns compassion, prayer and gratitude.',categories:['Christian Living'],category_ids:['living'],topics:['Discipleship'],issue:'Autumn 2024',issue_id:'2024',author:'Edward Martin',url:'/en/living/grace/'},
 {id:'two',title:'A café in Évora',body:'We sang in the café. Grace made us welcome.',categories:['Missions'],category_ids:['missions'],topics:['Portugal'],issue:'Spring 2023',issue_id:'2023',author:'A Writer',url:'/en/missions/cafe/'},
 {id:'three',title:'恩典与信仰',body:'每日的祈祷使我们更亲近神。',categories:['基督徒生活'],category_ids:['living'],topics:['信仰'],issue:'2024年夏季',issue_id:'2024',author:'作者',url:'/zh-Hans/living/test/'},
 {id:'four',title:'الإيمان والرجاء',body:'نتعلّم الصلاة والمحبة كل يوم.',categories:['الحياة المسيحية'],category_ids:['living'],topics:['صلاة'],issue:'خريف 2024',issue_id:'2024',author:'كاتب',url:'/ar/living/test/'}
]);
test('full body words found and link retained',()=>assert.equal(search(records,'compassion').results[0].url,'/en/living/grace/'));
test('category metadata searchable',()=>assert.equal(search(records,'missions').results[0].id,'two'));
test('topic metadata searchable',()=>assert.equal(search(records,'discipleship').results[0].id,'one'));
test('issue and byline metadata searchable',()=>{assert.equal(search(records,'autumn 2024').total,1);assert.equal(search(records,'edward').total,1)});
test('accent insensitive and composed/decomposed Unicode',()=>{assert.equal(search(records,'cafe evora').total,1);assert.equal(normalize('É'),'e')});
test('CJK substrings work without spaces',()=>assert.equal(search(records,'每日的祈祷').results[0].id,'three'));
test('RTL text searches directly',()=>assert.equal(search(records,'الصلاة').results[0].id,'four'));
test('title hits rank above body',()=>assert.equal(search(records,'grace').results[0].id,'one'));
test('category and issue filters combine',()=>assert.equal(search(records,'',{category:'living',issue:'2024'}).total,3));
test('filter mismatch gives empty result',()=>assert.equal(search(records,'grace',{issue:'other'}).total,0));
test('whitespace and repeated words normalized',()=>assert.deepEqual(tokenize('  grace Grace \n'),['grace']));
test('literal regex metacharacters do not throw',()=>assert.equal(search(records,'[a+').total,0));
test('saved language beats browser',()=>assert.equal(preferredLocale('af',['fr-FR'],['en','af','fr']),'af'));
test('browser language exact then supported base',()=>{assert.equal(preferredLocale(null,['fr-CA'],['en','fr']),'fr');assert.equal(preferredLocale(null,['zh-CN'],['en','zh-Hans']),'zh-Hans')});
test('unsupported or invalid preference falls back',()=>{assert.equal(preferredLocale('xx',['xx'],['en','fr']),'en');assert.equal(preferredLocale('xx',['fr'],['en','fr']),'fr')});
test('returned records exclude full bodies and prepared internals',()=>{const hit=search(records,'grace').results[0];assert.equal(hit.body,undefined);assert.equal(hit.normalizedBody,undefined)});

test('Indic vowel signs remain meaningful',()=>{assert.notEqual(normalize('दिन'),normalize('दन'));assert.notEqual(normalize('দিন'),normalize('দন'))});
test('all matching results can be paginated',()=>{const many=prepare(Array.from({length:90},(_,i)=>({...records[0],id:String(i)})));const next=search(many,'grace',{},40);assert.equal(next.total,90);assert.equal(next.results.length,40);assert.equal(next.offset,40);assert.equal(next.hasMore,true);assert.equal(search(many,'grace',{},80).results.length,10)});
