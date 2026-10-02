import test from 'node:test';
import assert from 'node:assert/strict';
import { normalize, tokenize, prepare, search, preferredLocale, bylineParts } from '../assets/search-core.js';
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

test('structured contributor names are searchable and carry only public links through worker results',()=>{
 const author={name:'Dean Taylor',url:'/af/authors/dean-taylor/',role:'Editor'};
 const hit=search(prepare([{...records[0],author:'~Bro. Dean',authors:[author]}]),'Dean Taylor').results[0];
 assert.equal(hit.author,'~Bro. Dean');
 assert.deepEqual(hit.authors,[{name:author.name,url:author.url,aliases:[]}]);
 assert.deepEqual(search(records,'grace').results[0].authors,[]);
});
test('byline links preserve repeated names, punctuation and every original character',()=>{
 const raw='By J. C. Ryle & C++ Writer; J. C. Ryle again.';
 const parts=bylineParts(raw,[{name:'J. C. Ryle',url:'/en/authors/j-c-ryle/'},{name:'C++ Writer',url:'/en/authors/c-writer/'}],'Author');
 assert.equal(parts.map(part=>part.text).join(''),raw);
 assert.deepEqual(parts.filter(part=>part.url).map(part=>part.text),['J. C. Ryle','C++ Writer']);
});
test('unprinted or boundary-mismatched credits follow unchanged text with localized label',()=>{
 const parts=bylineParts('By Annette and 李明',[{name:'Ann',url:'/af/authors/ann/'},{name:'李',url:'/af/authors/李/'}],'Skrywer');
 assert.equal(parts.map(part=>part.text).join(''),'By Annette and 李明 (Skrywer: Ann, 李)');
 assert.deepEqual(parts.filter(part=>part.url).map(part=>part.text),['Ann','李']);
});
test('longer overlapping names are credited without linking a substring as another person',()=>{
 const parts=bylineParts('John Smith',[{name:'John',url:'/en/authors/john/'},{name:'John Smith',url:'/en/authors/john-smith/'}],'Author');
 assert.equal(parts.map(part=>part.text).join(''),'John Smith (Author: John)');
 assert.deepEqual(parts.filter(part=>part.url).map(part=>part.text),['John Smith','John']);
});
test('raw-only attributions remain plain and unsafe link destinations are ignored',()=>{
 const raw='<img src=x onerror=alert(1)> Publisher';
 for(const authors of [[],[{name:'Publisher',url:'javascript:alert(1)'}],[{name:'Publisher',url:'//external.test/authors/x/'}]]){
  assert.deepEqual(bylineParts(raw,authors,'Author'),[{text:raw}]);
 }
 const parts=bylineParts(raw,[{name:'Publisher',url:'/en/authors/publisher/'}],'Author');
 assert.equal(parts.map(part=>part.text).join(''),raw);
 assert.equal(parts.filter(part=>part.url).length,1);
 assert.ok(parts.every(part=>Object.keys(part).every(key=>['text','url'].includes(key))));
});

test('reviewed name variants share one author link while preserving the complete printed credit',()=>{
 const author={name:'Dean Taylor',url:'/af/authors/dean-taylor/',aliases:['Bro. Dean','Brother Dean','Dean Taylor']};
 const raw='By Bro. Dean; Brother Dean, also known as Dean Taylor';
 const parts=bylineParts(raw,[author],'Skrywer');
 assert.equal(parts.map(part=>part.text).join(''),raw);
 assert.deepEqual(parts.filter(part=>part.url),[{text:'Bro. Dean',url:author.url}]);
 assert.deepEqual(bylineParts('Editorial',[author],'Skrywer').filter(part=>part.url),[{text:author.name,url:author.url}]);
 const prepared=prepare([{...records[0],author:'Dean Taylor',authors:[author]}]);
 for(const query of ['Dean Taylor','Brother Dean','Bro. Dean']) {
  const hit=search(prepared,query).results[0];
  assert.deepEqual(hit.authors,[author]);
  assert.equal(hit.url,records[0].url);
 }
});
