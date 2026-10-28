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
function update(){const t=types[type.value];$('#fieldHint').textContent=t.hint;$('#priceHint').textContent=window.LoveCatalog.label()+'：¥'+window.LoveCatalog.price(type.value)+(type.value==='strawberry'?'（拟定，筹备中）':'');const container=$('#specificFields');container.replaceChildren();for(const [id,label,placeholder] of t.fields){const wrap=document.createElement('label');wrap.textContent=label+' *';const field=document.createElement('textarea');field.id='detail-'+id;field.rows=id==='moments'||id==='places'||id==='letters'?5:3;field.maxLength=2000;field.placeholder=placeholder;field.required=true;wrap.append(field);container.append(wrap)}}
type.addEventListener('change',update);update();
const dialog=$('#orderDialog');let payload=null,receipt=null,copyText='',signature='',requestId='',busy=false;
const uuid=()=>crypto.randomUUID?crypto.randomUUID():Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join('');
function remember(){try{sessionStorage.setItem('love-intake-draft',JSON.stringify({payload,receipt,signature,requestId}))}catch{}}
try{const saved=JSON.parse(sessionStorage.getItem('love-intake-draft')||'null');if(saved?.payload){payload=saved.payload;receipt=saved.receipt;signature=saved.signature;requestId=saved.requestId;type.value=payload.product;update();$('#briefRecipient').value=payload.recipient;$('#briefDate').value=payload.desiredDate;$('#briefContact').value=payload.email;$('#materials').selectedIndex=['base','custom','unsure'].indexOf(payload.materials);$('#briefExtras').value=payload.extras;for(const [key,value] of Object.entries(payload.details))$('#detail-'+key).value=value}}catch{}
function error(message){$('#dialogError').textContent=message;$('#intakeError').textContent=dialog.open?'':message}
function lock(value){busy=value;['confirmOrder','claimPayment'].forEach(id=>$('#'+id).disabled=value)}
async function api(path,data,token){
 const endpoint=window.LoveIntake?.endpoint;
 if(!endpoint)throw Error('自动收单服务尚未启用。你的内容仍保留，可保存定制单副本，或联系页面邮箱。');
 const url=new URL(endpoint);if(url.protocol!=='https:'&&!['localhost','127.0.0.1'].includes(url.hostname))throw Error('收单地址配置有误，请联系页面邮箱。');
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),45000);
 try{const response=await fetch(endpoint.replace(/\/$/,'')+path,{method:'POST',headers:{'Content-Type':'application/json',...(token?{'X-Order-Token':token}:{})},body:JSON.stringify(data),signal:controller.signal});
 let result;try{result=await response.json()}catch{throw Error('服务未返回确认，请保留内容后重试。')}
 if(!response.ok)throw Error(result.error||'暂时无法提交，请稍后重试。');return result;
 }catch(e){if(e.name==='AbortError')throw Error('暂未收到确认。请勿重复付款，可点击原按钮重试提交。');throw e}finally{clearTimeout(timeout)}
}
function showSuccess(r){
 $('#orderReview').hidden=true;$('#paymentStep').hidden=true;$('#orderSuccess').hidden=false;$('#orderTitle').textContent='让故事，从这里继续。';$('#successNumber').textContent=r.id;
 $('#successText').textContent=r.quoteRequired?'你的需求已保存，需要先确认素材范围与报价，请暂勿付款。':'你的付款说明已提交，当前状态为「待人工核验」，尚未确认到账。';
 if(r.notificationStatus!=='sent')$('#successText').textContent+=' 邮件通知正在重试，需求已保留，请勿重复付款。';remember();
}
function showPayment(r){
 if(r.quoteRequired||['claimed','verified'].includes(r.paymentStatus)){showSuccess(r);return}
 $('#orderReview').hidden=true;$('#paymentStep').hidden=false;$('#orderTitle').textContent='把这份心意，慢慢兑现。';$('#paymentAmount').textContent='应付 ¥'+(r.amountMinor/100).toFixed(2);$('#orderNumber').textContent=r.id;
}
$('#briefForm').addEventListener('submit',e=>{
 e.preventDefault();if(busy)return;
 const t=types[type.value];const data={product:type.value,recipient:$('#briefRecipient').value.trim(),desiredDate:$('#briefDate').value,email:$('#briefContact').value.trim(),details:Object.fromEntries(t.fields.map(([id])=>[id,$('#detail-'+id).value.trim()])),materials:['base','custom','unsure'][$('#materials').selectedIndex],extras:$('#briefExtras').value.trim(),source:window.LoveSource||'未注明',website:$('#website').value};
 const next=JSON.stringify(data);if(signature!==next){signature=next;requestId=uuid();receipt=null}payload={...data,requestId};remember();
 const quote=data.materials!=='base'||data.product==='strawberry';
 copyText=['爱在ZJU · 定制单','礼物：'+t.name,'送给：'+data.recipient,'希望收到日期：'+data.desiredDate,'联系邮箱：'+data.email,quote?'需先报价，暂不付款':window.LoveCatalog.label()+'：¥'+window.LoveCatalog.price(type.value),...t.fields.map(([id,label])=>label+'：\n'+data.details[id]),'素材：'+$('#materials').value,'补充：'+(data.extras||'无')].join('\n\n');
 $('#reviewText').textContent=copyText;$('#orderReview').hidden=false;$('#paymentStep').hidden=true;$('#orderSuccess').hidden=true;$('#orderTitle').textContent='再看一眼，你的心意。';$('#confirmOrder').textContent=quote?'确认内容，提交报价咨询 →':'确认定制单，查看付款方式 →';error('');
 if(receipt)showPayment(receipt);dialog.showModal();
});
$('#confirmOrder').addEventListener('click',async()=>{if(busy)return;lock(true);error('');try{receipt=await api('/api/orders',payload);remember();showPayment(receipt)}catch(e){error(e.message)}finally{lock(false)}});
$('#claimPayment').addEventListener('click',async()=>{if(busy||!receipt)return;error('');if(!$('#paidDeclaration').checked||!$('#payerReference').value.trim()){error('请填写付款说明，并勾选付款声明。');return}lock(true);try{receipt=await api('/api/orders/'+receipt.id+'/payment-claim',{paidDeclaration:true,payerReference:$('#payerReference').value.trim()},receipt.accessToken);showSuccess(receipt)}catch(e){error(e.message)}finally{lock(false)}});
$('#closeOrder').addEventListener('click',()=>dialog.close());
$('#downloadOrder').addEventListener('click',()=>{const blob=new Blob([copyText+(receipt?'\n\n定制单编号：'+receipt.id:'')],{type:'text/plain;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='爱在ZJU-定制单.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});

})();
