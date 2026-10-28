(()=>{'use strict';
const $=s=>document.querySelector(s); let timer;
function toast(t){const el=$('#contactToast');el.textContent=t;el.classList.add('visible');clearTimeout(timer);timer=setTimeout(()=>el.classList.remove('visible'),3500)}
async function copy(text){try{if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(text);toast('复制好了，请主动发给我们。');return}}catch{}const active=document.activeElement;const t=document.createElement('textarea');t.value=text;t.style.cssText='position:fixed;left:0;top:0;width:1px;height:1px;opacity:0';document.body.append(t);t.select();let ok=false;try{ok=document.execCommand('copy')}catch{}t.remove();active?.focus();toast(ok?'已复制，请主动发给我们。':'请长按或选中文字手动复制。')}
document.querySelectorAll('[data-copy]').forEach(b=>b.addEventListener('click',()=>copy(b.dataset.copy)));
const birthdayFields=[['wish','祝福语（含生日或纪念日期）','例如：2026.11.01，愿你新的一岁平安快乐。'],['secret','许愿后出现的一句话','例如：希望你所有的愿望都慢慢实现。']];
const types={
 birthday:{name:'星空生日',price:'9.9',hint:'可修改收礼称呼、祝福语与日期，以及许愿后显示的文字。保留现有星空场景与动画。',fields:birthdayFields},
 strawberry:{name:'草莓生日（筹备中）',price:'9.9（拟定）',hint:'草莓风格尚未完成；拟修改称呼、祝福语与日期、许愿文字。提交后先咨询档期与实际效果。',fields:birthdayFields},
 memory:{name:'我们的N个瞬间',price:'19.9',hint:'基本款包含称呼、时间，以及最多5个瞬间的文字；保留样片照片。替换照片和额外改动另议。',fields:[['names','出现在页面上的名字和时间','例如：小满 × 阿澈，2023—2026'],['moments','最多5个瞬间的文字','按顺序填写：1. 时间／标题／故事／悄悄话；2. …']]},
 record:{name:'送你一张唱片',price:'15.9',hint:'基本款修改称呼、曲名和赠言，使用现有演示曲及封面；更换音频或封面另议。',fields:[['track','希望显示的曲名','例如：我们的晚风'],['message','想说的赠言','写下想随唱片一起送出的心意。']]},
 campus:{name:'青春有迹可循',price:'29.9',hint:'基本款可修改标题、年份，以及3—5个地点名称与故事文字；沿用现有地图和示意素材，照片替换另议。',fields:[['title','页面标题与年份','例如：我们的紫金港，2022—2026'],['places','3—5个地点及故事','按顺序填写：1. 地点／年份／故事；2. …']]},
 letters:{name:'大家的悄悄话',price:'29.9',hint:'基本款包含收礼称呼、开场寄语及最多5封信的署名与文字；沿用样片信封样式，照片另议。',fields:[['intro','开场寄语','例如：这些话，我们想一起送给你。'],['letters','最多5封信的署名与内容','按顺序填写：1. 署名／信件正文／可选悄悄话；2. …']]}
};
const type=$('#giftType'),initial=new URLSearchParams(location.search).get('product');if(initial&&types[initial])type.value=initial;
function update(){const t=types[type.value];$('#fieldHint').textContent=t.hint;$('#priceHint').textContent=window.LoveCatalog.label()+'：¥'+window.LoveCatalog.price(type.value)+(type.value==='strawberry'?'（拟定，筹备中）':'');const container=$('#specificFields');container.replaceChildren();for(const [id,label,placeholder] of t.fields){const wrap=document.createElement('label');wrap.textContent=label+' *';const field=document.createElement('textarea');field.id='detail-'+id;field.rows=id==='moments'||id==='places'||id==='letters'?5:3;field.maxLength=2000;field.placeholder=placeholder;field.required=true;wrap.append(field);container.append(wrap)}$('#briefResult').hidden=true}
type.addEventListener('change',update);update();
$('#briefForm').addEventListener('submit',e=>{e.preventDefault();const t=types[type.value],lines=t.fields.map(([id,label])=>label+'：\n'+$('#detail-'+id).value.trim());const text=['爱在ZJU · 定制单','',`来源：${window.LoveSource||'未注明'}`, `礼物：${t.name}`,`${window.LoveCatalog.label()}：¥${window.LoveCatalog.price(type.value)}`,`送给：${$('#briefRecipient').value.trim()}`,`希望收到日期：${$('#briefDate').value}`,`联系方式：${$('#briefContact').value.trim()}`,'',...lines.flatMap(x=>[x,'']),`照片／音频：${$('#materials').value}`,`补充说明：${$('#briefExtras').value.trim()||'无'}`,'','请确认素材范围、最终价格、付款方式、交付时间及修改次数。'].join('\n');$('#briefOutput').value=text;$('#emailBrief').href='mailto:loveshi1009@163.com?subject='+encodeURIComponent('爱在ZJU定制单｜'+t.name)+'&body='+encodeURIComponent(text);$('#briefResult').hidden=false;$('#briefResult').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth',block:'nearest'})});
$('#copyBrief').addEventListener('click',()=>copy($('#briefOutput').value));
})();
