/* Shared explicit project opening for CDP checks; startup intentionally stays empty. */
async function openSavedLab(evaluate, wait, click, id) {
  await wait('!!document.querySelector("#menu-experiment") && !document.querySelector("#access-dialog")?.open');
  if (!await evaluate('document.querySelector("#menu-experiment").getAttribute("aria-expanded") === "true"'))
    await click('#menu-experiment');
  await wait('!!document.querySelector("#open-lab") && !document.querySelector("#open-lab").disabled');
  await click('#open-lab');
  await wait('document.querySelector("#open-lab-dialog")?.open');
  const selector = id ? '.open-lab-item[data-lab-id=' + JSON.stringify(id) + ']' : '.open-lab-item';
  await wait(`!!document.querySelector(${JSON.stringify(selector)}) && !document.querySelector(${JSON.stringify(selector)}).disabled`);
  await click(selector);
  await click('#confirm-open-lab');
  await wait('!document.querySelector("#open-lab-dialog").open');
}

async function experimentAction(evaluate, wait, click, selector) {
  if (!await evaluate('document.querySelector("#menu-experiment").getAttribute("aria-expanded") === "true"'))
    await click('#menu-experiment');
  await wait(`!!document.querySelector(${JSON.stringify(selector)}) && !document.querySelector(${JSON.stringify(selector)}).disabled`);
  await click(selector);
}

async function openImageManager(evaluate, wait, click) {
  await wait('!!document.querySelector("#menu-tools") && !document.querySelector("#access-dialog")?.open');
  if (!await evaluate('document.querySelector("#menu-tools").getAttribute("aria-expanded") === "true"'))
    await click('#menu-tools');
  await wait('!!document.querySelector("#menu-images")');
  await click('#menu-images');
  await wait('document.querySelector("#image-manager")?.open');
}

module.exports = { openSavedLab, experimentAction, openImageManager };
