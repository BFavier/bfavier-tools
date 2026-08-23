from aiobotocore.session import get_session, AioBaseClient
from botocore.exceptions import ClientError
from typing import Literal


class Cognito:
    """
    >>> self.client = Cognito()
    >>> await ecognitocs.open()
    >>> ...
    >>> await self.client.close()

    It can also be used as an async context
    >>> async with Cognito() as self.client:
    >>>     ...
    """

    def __init__(self):
        self.session = get_session()
        self._client: AioBaseClient | None = None

    async def open(self):
        self._client = await self.session.create_client("cognito-idp").__aenter__()

    async def close(self):
        await self._client.__aexit__(None, None, None)
        self._client = None

    async def __aenter__(self) -> "Cognito":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    @property
    def client(self) -> AioBaseClient:
        if self._client is None:
            raise RuntimeError(f"{type(self).__name__} object is not initialized")
        else:
            return self._client

    async def create_user_pool_async(self, pool_name: str) -> str:
        """
        Create an user pool
        """
        user_pool_response = await self.client.create_user_pool(
            PoolName=pool_name,
        )
        return user_pool_response['UserPool']['Id']

    async def create_user_pool_client_async(self, pool_id: str, pool_client_name: str) -> str:
        """
        Create an user pool client
        """
        user_pool_client_response = await self.client.create_user_pool_client(
            UserPoolId=pool_id,
            ClientName=pool_client_name,
            GenerateSecret=False
        )
        return user_pool_client_response['UserPoolClient']['ClientId']

    async def delete_user_pool_client_async(self, pool_id: str, pool_client_id: str):
        await self.client.delete_user_pool_client(
            UserPoolId=pool_id,
            ClientId=pool_client_id
        )

    async def delete_user_pool_async(self, pool_id: str):
        await self.client.delete_user_pool(
            UserPoolId=pool_id
        )


    async def login_async(self, pool_client: str, user: str, password: str) -> dict:
        """
        Return the authentification tokens
        """
        return await self.client.initiate_auth(
            ClientId=pool_client,
            AuthFlow='USER_PASSWORD_AUTH',  # replace for SRP at one point ?
            AuthParameters={'USERNAME': user, 'PASSWORD': password}
        )


    async def validate_mfa_async(self, pool_client: str, user: str, session_token: str, mfa_code: str):
        """
        2nd step of user authentication
        """
        await self.client.respond_to_auth_challenge(
            ClientId=pool_client,
            ChallengeName='SMS_MFA',
            Session=self.session,
            ChallengeResponses={'SMS_MFA_CODE': mfa_code, 'USERNAME': user}
        )


    async def refresh_access_token_async(self, pool_client: str, refresh_token: str) -> str:
        """
        return a new access token using the refresh token
        """
        response = await self.client.initiate_auth(
            ClientId=pool_client,
            AuthFlow='REFRESH_TOKEN_AUTH',
            AuthParameters={'REFRESH_TOKEN': refresh_token}
        )
        return response['AuthenticationResult']['AccessToken']


    async def logout_async(self, access_token: str):
        """
        invalidates all sessions of the authenticated user
        """
        await self.client.global_sign_out(AccessToken=access_token)


    async def sign_up_async(self, pool_client: str, user: str, password: str, attributes: dict = {}):
        """
        Allows to create an account linked to the given email
        """
        await self.client.sign_up(
            ClientId=pool_client,
            Username=user,
            Password=password,
            UserAttributes=[{"Name": k, "Value": v} for k, v in attributes.items()]
        )


    async def confirm_signup_email_async(self, pool_client: str, user: str, confirmation_code: str):
        """
        confirms the email after having signed up
        """
        await self.client.confirm_sign_up(
            ClientId=pool_client,
            Username=user,
            ConfirmationCode=confirmation_code
        )


    async def send_confirmation_code_async(self, access_token: str, medium: Literal["email", "phone_number"]):
        """
        send (or resend) a confirmation sms or email to verify that user has access to it
        """
        await self.client.get_user_attribute_verification_code(
            AccessToken=access_token,
            AttributeName=medium
        )


    async def verify_confirmation_code_async(self, access_token: str, medium: Literal["email", "phone_number"], code: str):
        """
        validate the email or phone number
        """
        await self.client.verify_user_attribute(
            AccessToken=access_token,
            AttributeName=medium,
            Code=code
        )


    async def admin_setup_mfa_async(self, user_pool: str, user: str, enabled: bool):
        """
        setup the MFA for the given user
        """
        await self.client.set_user_mfa_preference(
            SMSMfaSettings={'Enabled': enabled, 'PreferredMfa': True},
            Username=user,
            UserPoolId=user_pool
        )


    async def get_user_infos_async(self, access_token: str) -> dict:
        """
        returns all the attributes and more of an user
        """
        infos = await self.client.get_user(AccessToken=access_token)
        infos["UserAttributes"] = {d["Name"]: d["Value"] for d in infos["UserAttributes"]}
        return infos


    async def set_attribute_async(self, access_token: str, attributes: dict):
        """
        set the given attributes to an user
        """
        await self.client.update_user_attributes(
            AccessToken=access_token,
            UserAttributes=[{'Name': k,'Value': v} for k, v in attributes.items()]
        )


    async def admin_get_user_infos_async(self, user_pool: str, user: str) -> dict | None:
        """
        returns all the attributes and more of an user
        returns None if the user does not exist
        """
        try:
            infos = await self.client.admin_get_user(UserPoolId=user_pool, Username=user)
        except ClientError as e:
            if e.response["Error"]["Code"] == "UserNotFoundException":
                return None
            else:
                raise e
        infos["UserAttributes"] = {d["Name"]: d["Value"] for d in infos["UserAttributes"]}
        return infos


    async def admin_set_attributes_async(self, user_pool: str, user: str, attributes: dict):
        """
        set the given attributes to an user

        Example
        -------
        >>> admin_set_attributes("eu-west-3_cFEWVr9Hx", "test-user", attributes={"custom:uuid": "test-uuid"})
        """
        await self.client.admin_update_user_attributes(
            UserPoolId=user_pool,
            Username=user,
            UserAttributes=[{'Name': k,'Value': v}for k, v in attributes.items()],
        )


    async def admin_sign_up_async(self, user_pool: str, user: str, password: str, attributes: dict={}):
        """
        Creates an account without sending email verification.
        This does not send a confirmation email, {"email_verified": "true"} should be part of the attributes.

        Example
        -------
        >>> admin_signup("eu-west-3_cFEWVr9Hx", "test-user", attributes={"email": "test@mail.com", "email_verified": "true"})
        """
        await self.client.admin_create_user(
            UserPoolId=user_pool,
            Username=user,
            UserAttributes=[{"Name": k, "Value": v} for k, v in attributes.items()],
            MessageAction="SUPPRESS"  # Prevents the user from receiving the default welcome email
        )
        await self.client.admin_set_user_password(
            UserPoolId=user_pool,
            Username=user,
            Password=password,
            Permanent=True
        )
        await self.admin_enable_disable_user_async(user_pool, user, enabled=True)


    async def admin_resend_account_confirmation_email_async(self, pool_client: str, user: str):
        """
        resend the account confirmation email
        """
        await self.client.resend_confirmation_code(
            ClientId=pool_client,
            Username=user
        )


    async def admin_confirm_status_async(self, user_pool: str, user: str):
        """
        Set user status to 'Confirmed' if the user is in 'Pending confirmation' or 'Force change password'.
        Will raise an error if the user is already confirmed.
        """
        await self.client.admin_confirm_sign_up(
            UserPoolId=user_pool,
            Username=user,
        )


    async def admin_enable_disable_user_async(self, user_pool: str, user: str, enabled: bool):
        """
        Disable an account
        """
        if enabled:
            await self.client.admin_enable_user(UserPoolId=user_pool, Username=user)
        else:
            await self.client.admin_disable_user(UserPoolId=user_pool, Username=user)


    async def admin_delete_user_async(self, user_pool: str, user: str):
        """
        Delete an account
        """
        await self.client.admin_delete_user(UserPoolId=user_pool, Username=user)


    async def admin_resend_confirmation_email_async(self, user_pool: str, user: str):
        """
        Only works if the user is in 'FORCE_CHANGE_PASSWORD' state (has just been created and never logged in)
        """
        try:
            await self.client.admin_create_user(
                UserPoolId=user_pool,
                Username=user,
                MessageAction='RESEND'
            )
        except Exception as e:
            raise e


    async def admin_forgot_password_async(self, pool_client: str, user: str):
        """
        Sends a password reset confirmation code by email
        """
        await self.client.forgot_password(
            ClientId=pool_client,
            Username=user
        )


    async def admin_confirm_forgot_password_async(self, pool_client: str, user: str, code: str, password: str):
        """
        Reset the password of an user, confirmed using the confirmation code received by email
        """
        await self.client.confirm_forgot_password(
            ClientId=pool_client,
            Username=user,
            ConfirmationCode=code,
            Password=password
        )


if __name__ == "__main__":
    import IPython
    IPython.embed()
