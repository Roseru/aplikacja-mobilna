<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=true; section>
  <#if section == "header">${msg("calorieEmailProofTitle")}
  <#elseif section == "form">
    <#if emailProofSent??><p role="status">${msg("calorieEmailProofSent")}</p></#if>
    <form id="calorie-email-proof" action="${url.loginAction}" method="post">
      <label for="email">${msg("email")}</label>
      <input id="email" name="email" type="email" autocomplete="email" maxlength="254" required autofocus>
      <button type="submit">${msg("calorieEmailProofSend")}</button>
    </form>
    <p><a href="${url.loginUrl}">${msg("backToLogin")}</a></p>
  </#if>
</@layout.registrationLayout>
