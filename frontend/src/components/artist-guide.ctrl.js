import {user} from '../state/user.js';

const ArtistGuideCtrl = app => async () => ({
  appName: 'Wonky Studio',
  user: user.current,
});

export {ArtistGuideCtrl};
