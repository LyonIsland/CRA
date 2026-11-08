const {chromium}=require('playwright');
const path=require('path'),fs=require('fs');
(async()=>{
 const dir=path.resolve(__dirname,'../assets/manuals/step_wall6');
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1000,height:1200}});
  await page.goto('file:///'+path.join(dir,'manual.html').replaceAll('\\','/'),{waitUntil:'load'});
  await page.pdf({path:path.join(dir,'manual.pdf'),format:'A4',printBackground:true,preferCSSPageSize:true});
  await page.screenshot({path:path.join(dir,'cover.png')});
  const pages=(fs.readFileSync(path.join(dir,'manual.pdf')).toString('latin1').match(/\/Type\s*\/Page\b/g)||[]).length;
  if(pages!==8)throw new Error('Expected 8 illustrated pages, got '+pages);
  console.log(JSON.stringify({pages,pdf:path.join(dir,'manual.pdf')}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
