import {loginUrl, user} from '../state/user.js';

const NotAuthorizedCtrl = () => async () => {
  const params = new URLSearchParams(window.location.search);
  const inviteToken = params.get('invite') ?? '';
  return {
    appName: 'Wonky Studio',
    organizationId: user.organizationId,
    loginUrl: loginUrl(inviteToken),
    inviteToken
  };
};

export {NotAuthorizedCtrl};
