import activityIcon from 'lucide-static/icons/activity.svg?raw';
import arrowDownIcon from 'lucide-static/icons/arrow-down.svg?raw';
import arrowUpIcon from 'lucide-static/icons/arrow-up.svg?raw';
import audioLinesIcon from 'lucide-static/icons/audio-lines.svg?raw';
import captionsIcon from 'lucide-static/icons/captions.svg?raw';
import clapperboardIcon from 'lucide-static/icons/clapperboard.svg?raw';
import externalLinkIcon from 'lucide-static/icons/external-link.svg?raw';
import imageMinusIcon from 'lucide-static/icons/image-minus.svg?raw';
import imagesIcon from 'lucide-static/icons/images.svg?raw';
import logOutIcon from 'lucide-static/icons/log-out.svg?raw';
import packageIcon from 'lucide-static/icons/package.svg?raw';
import playIcon from 'lucide-static/icons/play.svg?raw';
import scanSearchIcon from 'lucide-static/icons/scan-search.svg?raw';
import settings2Icon from 'lucide-static/icons/settings-2.svg?raw';
import sparklesIcon from 'lucide-static/icons/sparkles.svg?raw';
import trash2Icon from 'lucide-static/icons/trash-2.svg?raw';
import uploadIcon from 'lucide-static/icons/upload.svg?raw';
import workflowIcon from 'lucide-static/icons/workflow.svg?raw';

const ICONS = {
  activity: activityIcon,
  'arrow-down': arrowDownIcon,
  'arrow-up': arrowUpIcon,
  'audio-lines': audioLinesIcon,
  captions: captionsIcon,
  clapperboard: clapperboardIcon,
  'external-link': externalLinkIcon,
  'image-minus': imageMinusIcon,
  images: imagesIcon,
  'log-out': logOutIcon,
  package: packageIcon,
  play: playIcon,
  'scan-search': scanSearchIcon,
  'settings-2': settings2Icon,
  sparkles: sparklesIcon,
  'trash-2': trash2Icon,
  upload: uploadIcon,
  workflow: workflowIcon,
};

function hydrateIcons(root = document) {
  const scope = root instanceof Element || root instanceof Document ? root : document;
  scope.querySelectorAll?.('[data-icon]').forEach(element => {
    const name = element.getAttribute('data-icon') || '';
    const svg = ICONS[name];
    if (!svg) return;
    if (element.dataset.iconHydrated === name) return;
    element.innerHTML = svg;
    element.dataset.iconHydrated = name;
    element.setAttribute('aria-hidden', 'true');
  });
}

export {hydrateIcons};
